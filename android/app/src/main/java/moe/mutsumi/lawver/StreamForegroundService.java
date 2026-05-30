package moe.mutsumi.lawver;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
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
    // 非续传流保留有限读超时，避免真断线后永远阻塞；续传流会改用无限读超时，
    // 因为服务端缓冲续传可以在前端恢复时主动兜底，原生层不应把安静阶段误判成失败。
    private static final int FALLBACK_READ_TIMEOUT_MS = 45000;
    private static final Map<String, StreamSession> SESSIONS = new ConcurrentHashMap<>();
    private final ExecutorService executor = Executors.newCachedThreadPool();

    static class DrainResult {
        final List<String> events;
        final int nextIndex;
        final boolean done;
        final String error;
        final boolean hasMore;

        DrainResult(List<String> events, int nextIndex, boolean done, String error, boolean hasMore) {
            this.events = events;
            this.nextIndex = nextIndex;
            this.done = done;
            this.error = error;
            this.hasMore = hasMore;
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

        DrainResult drain(int fromIndex, int maxEvents) {
            synchronized (events) {
                int start = Math.max(0, Math.min(fromIndex, events.size()));
                int end = maxEvents > 0 ? Math.min(events.size(), start + maxEvents) : events.size();
                boolean hasMore = end < events.size();
                boolean drainedDone = done && !hasMore;
                List<String> slice = new ArrayList<>(events.subList(start, end));
                return new DrainResult(slice, end, drainedDone, drainedDone ? error : null, hasMore);
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

    /** 列出当前进程内仍存活的 session id（含已 done 但尚未 stop 的），供 WebView 重建后重新接上。 */
    static java.util.List<String> listActiveStreamIds() {
        return new ArrayList<>(SESSIONS.keySet());
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

    static DrainResult drain(String streamId, int fromIndex, int maxEvents) {
        StreamSession session = SESSIONS.get(streamId);
        if (session == null) {
            return new DrainResult(new ArrayList<>(), fromIndex, true, "native stream is unavailable", false);
        }
        return session.drain(fromIndex, maxEvents);
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
            boolean resumeEnabled = isResumeEnabled(body);
            connection.setReadTimeout(resumeEnabled ? 0 : FALLBACK_READ_TIMEOUT_MS);
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
            finishSession(session, "连接超时，可能已断开（" + (FALLBACK_READ_TIMEOUT_MS / 1000) + "s 内无数据）");
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

    private boolean isResumeEnabled(String body) {
        try {
            return new JSONObject(body).optBoolean("resume_enabled", false);
        } catch (Exception ignored) {
            return false;
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

    /** 点按通知回到应用：复用既有任务栈（MainActivity 为 singleTask），不新建实例。 */
    private PendingIntent buildContentIntent() {
        Intent launch = new Intent(this, MainActivity.class);
        launch.setAction(Intent.ACTION_MAIN);
        launch.addCategory(Intent.CATEGORY_LAUNCHER);
        launch.addFlags(
            Intent.FLAG_ACTIVITY_NEW_TASK |
            Intent.FLAG_ACTIVITY_CLEAR_TOP |
            Intent.FLAG_ACTIVITY_SINGLE_TOP |
            Intent.FLAG_ACTIVITY_REORDER_TO_FRONT
        );
        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        return PendingIntent.getActivity(this, 0, launch, flags);
    }

    private Notification buildNotification() {
        NotificationCompat.Builder builder = new NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(getApplicationInfo().icon)
            .setContentTitle("Lawver 正在生成回答")
            .setContentText("离开页面后仍会继续接收本次回答，点按可返回应用。")
            .setContentIntent(buildContentIntent())
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW);

        // Android 16 (API 36) Live Update：将常驻通知提升为“持续进行中”活动，
        // 在状态栏/锁屏以更醒目的形式呈现“正在生成”，并显示不确定进度条。
        // 这些 API 由 androidx.core 1.16.0 提供，旧系统上回退为普通常驻低优先级通知。
        if (Build.VERSION.SDK_INT >= 36) {
            builder
                .setStyle(new NotificationCompat.ProgressStyle().setProgressIndeterminate(true))
                .setRequestPromotedOngoing(true)
                .setShortCriticalText("生成中");
        }
        return builder.build();
    }
}
