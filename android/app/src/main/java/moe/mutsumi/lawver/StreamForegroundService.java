package moe.mutsumi.lawver;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.os.IBinder;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationCompat;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.OutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Iterator;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

public class StreamForegroundService extends Service {
    static final String ACTION_START_STREAM = "moe.mutsumi.lawver.stream.START";
    static final String ACTION_STOP_STREAM = "moe.mutsumi.lawver.stream.STOP";
    static final String EXTRA_STREAM_ID = "streamId";
    static final String EXTRA_URL = "url";
    static final String EXTRA_HEADERS = "headers";
    static final String EXTRA_BODY = "body";

    private static final String CHANNEL_ID = "lawver_stream_generation";
    private static final String NATIVE_ORIGIN = "capacitor://localhost";
    private static final int NOTIFICATION_ID = 5107;
    private static final int CONNECT_TIMEOUT_MS = 10000;
    // 有限读超时：配合服务端的 SSE 心跳（": ping"，约 15s 一次）使用。
    // 心跳会持续重置该超时，因此只有连接真正死亡（熄屏 doze、网络切换、NAT 回收等）
    // 才会触发 SocketTimeoutException，从而避免"已断流却永远阻塞在 readLine"的误导态。
    private static final int READ_TIMEOUT_MS = 45000;
    private static final Map<String, StreamSession> SESSIONS = new ConcurrentHashMap<>();
    private final ExecutorService executor = Executors.newCachedThreadPool();

    static class DrainResult {
        final List<String> events;
        final int nextIndex;
        final boolean done;
        final String error;

        DrainResult(List<String> events, int nextIndex, boolean done, String error) {
            this.events = events;
            this.nextIndex = nextIndex;
            this.done = done;
            this.error = error;
        }
    }

    private static class StreamSession {
        final String streamId;
        final List<String> events = new ArrayList<>();
        volatile boolean done = false;
        volatile String error = null;
        volatile HttpURLConnection connection = null;

        StreamSession(String streamId) {
            this.streamId = streamId;
        }

        int addEvent(String payload) {
            synchronized (events) {
                events.add(payload);
                return events.size() - 1;
            }
        }

        DrainResult drain(int fromIndex) {
            synchronized (events) {
                int start = Math.max(0, Math.min(fromIndex, events.size()));
                List<String> slice = new ArrayList<>(events.subList(start, events.size()));
                return new DrainResult(slice, events.size(), done, error);
            }
        }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannel();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        startForegroundCompat();
        if (intent == null) return START_NOT_STICKY;
        String action = intent.getAction();
        String streamId = intent.getStringExtra(EXTRA_STREAM_ID);
        if (ACTION_STOP_STREAM.equals(action)) {
            stopStreamInternal(streamId);
            return START_NOT_STICKY;
        }
        if (ACTION_START_STREAM.equals(action)) {
            String url = intent.getStringExtra(EXTRA_URL);
            String body = intent.getStringExtra(EXTRA_BODY);
            String headers = intent.getStringExtra(EXTRA_HEADERS);
            if (streamId != null && url != null && body != null) {
                StreamSession session = register(streamId);
                executor.execute(() -> runStream(session, url, headers, body));
            }
        }
        return START_NOT_STICKY;
    }

    private void startForegroundCompat() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(
                NOTIFICATION_ID,
                buildNotification(),
                android.content.pm.ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
            );
        } else {
            startForeground(NOTIFICATION_ID, buildNotification());
        }
    }

    @Nullable
    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }

    @Override
    public void onDestroy() {
        for (StreamSession session : SESSIONS.values()) {
            if (session.connection != null) {
                session.connection.disconnect();
            }
        }
        executor.shutdownNow();
        super.onDestroy();
    }

    /** 由插件在启动前台服务前同步调用，确保 session 已登记，避免 drain 竞态误判。 */
    static StreamSession register(String streamId) {
        StreamSession session = SESSIONS.get(streamId);
        if (session == null) {
            session = new StreamSession(streamId);
            SESSIONS.put(streamId, session);
        }
        return session;
    }

    static DrainResult drain(String streamId, int fromIndex) {
        StreamSession session = SESSIONS.get(streamId);
        if (session == null) {
            return new DrainResult(new ArrayList<>(), fromIndex, true, "native stream is unavailable");
        }
        return session.drain(fromIndex);
    }

    static void stopStream(Context context, String streamId) {
        Intent intent = new Intent(context, StreamForegroundService.class);
        intent.setAction(ACTION_STOP_STREAM);
        intent.putExtra(EXTRA_STREAM_ID, streamId);
        context.startService(intent);
    }

    private void stopStreamInternal(String streamId) {
        StreamSession session = SESSIONS.remove(streamId);
        if (session != null && session.connection != null) {
            session.connection.disconnect();
        }
        if (SESSIONS.isEmpty()) {
            stopForeground(true);
            stopSelf();
        }
    }

    private void runStream(StreamSession session, String rawUrl, String rawHeaders, String body) {
        HttpURLConnection connection = null;
        try {
            URL url = new URL(rawUrl);
            connection = (HttpURLConnection) url.openConnection();
            session.connection = connection;
            connection.setRequestMethod("POST");
            connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
            // SSE responses may stay quiet while the model is thinking or a tool is running.
            connection.setReadTimeout(READ_TIMEOUT_MS);
            connection.setDoOutput(true);
            connection.setRequestProperty("Accept", "text/event-stream");
            connection.setRequestProperty("Origin", NATIVE_ORIGIN);
            connection.setRequestProperty("Referer", NATIVE_ORIGIN + "/");
            connection.setRequestProperty("X-Lawver-Client", "capacitor");
            applyHeaders(connection, rawHeaders);

            byte[] bodyBytes = body.getBytes(StandardCharsets.UTF_8);
            connection.setFixedLengthStreamingMode(bodyBytes.length);
            try (OutputStream output = connection.getOutputStream()) {
                output.write(bodyBytes);
            }

            int status = connection.getResponseCode();
            InputStream input = status >= 200 && status < 300
                ? connection.getInputStream()
                : connection.getErrorStream();
            if (status < 200 || status >= 300) {
                throw new IllegalStateException("HTTP " + status + ": " + readAll(input));
            }

            try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
                String line;
                while ((line = reader.readLine()) != null) {
                    if (!line.startsWith("data: ")) continue;
                    String payload = line.substring(6).trim();
                    if (payload.isEmpty()) continue;
                    if ("[DONE]".equals(payload)) {
                        finishSession(session, null);
                        return;
                    }
                    int index = session.addEvent(payload);
                    StreamServicePlugin.notifyStreamEvent(session.streamId, index, payload);
                }
            }
            // 读到 EOF 但从未收到 [DONE]：连接被中途切断，按错误结束（而非当成正常完成），
            // 否则会把被截断的回答显示成"已完整"。
            finishSession(session, "连接已中断（未收到完成标记）");
        } catch (java.net.SocketTimeoutException ex) {
            finishSession(session, "连接超时，可能已断开（" + (READ_TIMEOUT_MS / 1000) + "s 内无数据）");
        } catch (Exception ex) {
            finishSession(session, ex.getMessage());
        } finally {
            if (connection != null) {
                connection.disconnect();
            }
            session.connection = null;
        }
    }

    private void finishSession(StreamSession session, String error) {
        session.done = true;
        session.error = error;
        StreamServicePlugin.notifyStreamDone(session.streamId, session.events.size(), error);
    }

    private void applyHeaders(HttpURLConnection connection, String rawHeaders) throws Exception {
        if (rawHeaders == null || rawHeaders.trim().isEmpty()) return;
        JSONObject headers = new JSONObject(rawHeaders);
        Iterator<String> keys = headers.keys();
        while (keys.hasNext()) {
            String key = keys.next();
            String value = headers.optString(key, "");
            if (!key.trim().isEmpty() && !value.isEmpty()) {
                connection.setRequestProperty(key, value);
            }
        }
    }

    private String readAll(InputStream input) throws Exception {
        if (input == null) return "";
        StringBuilder builder = new StringBuilder();
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(input, StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                builder.append(line).append('\n');
            }
        }
        return builder.toString();
    }

    private void createNotificationChannel() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return;
        NotificationChannel channel = new NotificationChannel(
            CHANNEL_ID,
            "Lawver 生成中",
            NotificationManager.IMPORTANCE_LOW
        );
        channel.setDescription("后台接收正在生成的回答");
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager != null) {
            manager.createNotificationChannel(channel);
        }
    }

    private Notification buildNotification() {
        return new NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(getApplicationInfo().icon)
            .setContentTitle("Lawver 正在生成回答")
            .setContentText("离开页面后仍会继续接收本次回答。")
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build();
    }
}
