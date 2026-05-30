package moe.mutsumi.lawver;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.os.Build;

import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;

import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.UUID;

@CapacitorPlugin(name = "StreamService")
public class StreamServicePlugin extends Plugin {
    private static StreamServicePlugin instance;

    @Override
    public void load() {
        instance = this;
    }

    @PluginMethod
    public void requestNotificationPermission(PluginCall call) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU) {
            JSObject result = new JSObject();
            result.put("granted", true);
            call.resolve(result);
            return;
        }
        boolean granted = ContextCompat.checkSelfPermission(getContext(), Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED;
        if (!granted && getActivity() != null) {
            ActivityCompat.requestPermissions(getActivity(), new String[]{Manifest.permission.POST_NOTIFICATIONS}, 4107);
        }
        JSObject result = new JSObject();
        result.put("granted", granted);
        call.resolve(result);
    }

    @PluginMethod
    public void startStream(PluginCall call) {
        String url = call.getString("url");
        String body = call.getString("body");
        JSObject headers = call.getObject("headers", new JSObject());
        if (url == null || url.trim().isEmpty() || body == null) {
            call.reject("url and body are required", "BAD_INPUT");
            return;
        }

        String streamId = "native_" + UUID.randomUUID().toString().replace("-", "");
        // 先同步登记 session，避免前台服务异步启动期间 JS 端 drain 把"尚未注册"误判成终态。
        StreamForegroundService.register(streamId);
        Intent intent = new Intent(getContext(), StreamForegroundService.class);
        intent.setAction(StreamForegroundService.ACTION_START_STREAM);
        intent.putExtra(StreamForegroundService.EXTRA_STREAM_ID, streamId);
        intent.putExtra(StreamForegroundService.EXTRA_URL, url);
        intent.putExtra(StreamForegroundService.EXTRA_BODY, body);
        intent.putExtra(StreamForegroundService.EXTRA_HEADERS, headers.toString());
        ContextCompat.startForegroundService(getContext(), intent);

        JSObject result = new JSObject();
        result.put("streamId", streamId);
        call.resolve(result);
    }

    @PluginMethod
    public void listActive(PluginCall call) {
        JSObject result = new JSObject();
        JSArray ids = new JSArray();
        for (String id : StreamForegroundService.listActiveStreamIds()) {
            ids.put(id);
        }
        result.put("streamIds", ids);
        call.resolve(result);
    }

    @PluginMethod
    public void drain(PluginCall call) {
        String streamId = call.getString("streamId");
        Integer fromIndex = call.getInt("fromIndex", 0);
        if (streamId == null || streamId.trim().isEmpty()) {
            call.reject("streamId is required", "BAD_INPUT");
            return;
        }

        Integer maxEvents = call.getInt("maxEvents", 0);
        StreamForegroundService.DrainResult drained = StreamForegroundService.drain(
            streamId,
            fromIndex == null ? 0 : fromIndex,
            maxEvents == null ? 0 : maxEvents
        );
        JSObject result = new JSObject();
        JSArray events = new JSArray();
        for (String event : drained.events) {
            events.put(event);
        }
        result.put("events", events);
        result.put("nextIndex", drained.nextIndex);
        result.put("done", drained.done);
        result.put("hasMore", drained.hasMore);
        if (drained.error != null) {
            result.put("error", drained.error);
        }
        call.resolve(result);
    }

    @PluginMethod
    public void stop(PluginCall call) {
        String streamId = call.getString("streamId");
        if (streamId == null || streamId.trim().isEmpty()) {
            call.reject("streamId is required", "BAD_INPUT");
            return;
        }
        StreamForegroundService.stopStream(getContext(), streamId);
        call.resolve();
    }

    static void notifyStreamEvent(String streamId, int index, String payload) {
        StreamServicePlugin plugin = instance;
        if (plugin == null) return;
        JSObject event = new JSObject();
        event.put("streamId", streamId);
        event.put("index", index);
        event.put("payload", payload);
        plugin.notifyListeners("streamEvent", event);
    }

    static void notifyStreamDone(String streamId, int finalIndex, String error) {
        StreamServicePlugin plugin = instance;
        if (plugin == null) return;
        JSObject event = new JSObject();
        event.put("streamId", streamId);
        event.put("finalIndex", finalIndex);
        if (error != null) {
            event.put("error", error);
        }
        plugin.notifyListeners("streamDone", event);
    }
}
