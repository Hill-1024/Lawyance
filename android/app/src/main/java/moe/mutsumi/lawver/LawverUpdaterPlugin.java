package moe.mutsumi.lawver;

import android.app.DownloadManager;
import android.content.Context;
import android.content.Intent;
import android.database.Cursor;
import android.net.Uri;
import android.os.Build;
import android.os.Environment;
import android.provider.Settings;

import androidx.core.content.FileProvider;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import org.json.JSONObject;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;
import java.util.Locale;

@CapacitorPlugin(name = "LawverUpdater")
public class LawverUpdaterPlugin extends Plugin {
    private static final String APK_MIME = "application/vnd.android.package-archive";
    private static final int CONNECT_TIMEOUT_MS = 10000;
    private static final int READ_TIMEOUT_MS = 20000;

    @PluginMethod
    public void checkForUpdate(PluginCall call) {
        String manifestUrl = call.getString("manifestUrl");
        if (manifestUrl == null || manifestUrl.trim().isEmpty()) {
            call.reject("manifestUrl is required", "BAD_INPUT");
            return;
        }

        execute(() -> {
            HttpURLConnection connection = null;
            try {
                URL url = new URL(manifestUrl);
                connection = (HttpURLConnection) url.openConnection();
                connection.setConnectTimeout(CONNECT_TIMEOUT_MS);
                connection.setReadTimeout(READ_TIMEOUT_MS);
                connection.setRequestProperty("Accept", "application/json");
                connection.setRequestProperty("X-Lawver-Client", "capacitor");
                int status = connection.getResponseCode();
                if (status < 200 || status >= 300) {
                    call.reject("Version check failed with HTTP " + status, String.valueOf(status));
                    return;
                }
                String body = readAll(connection.getInputStream());
                call.resolve(JSObject.fromJSONObject(new JSONObject(body)));
            } catch (Exception ex) {
                call.reject("Version check failed", "CHECK_FAILED", ex);
            } finally {
                if (connection != null) {
                    connection.disconnect();
                }
            }
        });
    }

    @PluginMethod
    public void downloadApk(PluginCall call) {
        String url = call.getString("url");
        String fileName = sanitizeFileName(call.getString("fileName", "Lawver.apk"));
        String expectedSha256 = call.getString("sha256", "");
        if (url == null || url.trim().isEmpty()) {
            call.reject("url is required", "BAD_INPUT");
            return;
        }

        DownloadManager manager = (DownloadManager) getContext().getSystemService(Context.DOWNLOAD_SERVICE);
        if (manager == null) {
            call.reject("DownloadManager is unavailable", "UNAVAILABLE");
            return;
        }

        File downloadsDir = Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_DOWNLOADS);
        if (!downloadsDir.exists() && !downloadsDir.mkdirs()) {
            call.reject("Cannot access system Downloads directory", "DOWNLOAD_DIR_FAILED");
            return;
        }
        File target = new File(downloadsDir, fileName);
        if (target.exists() && !target.delete()) {
            call.reject("Cannot replace existing APK in Downloads", "DOWNLOAD_TARGET_BUSY");
            return;
        }

        try {
            DownloadManager.Request request = new DownloadManager.Request(Uri.parse(url));
            request.setTitle(fileName);
            request.setDescription("Lawver 正在下载更新包");
            request.setMimeType(APK_MIME);
            request.setNotificationVisibility(DownloadManager.Request.VISIBILITY_VISIBLE_NOTIFY_COMPLETED);
            request.setDestinationUri(Uri.fromFile(target));
            request.setAllowedOverMetered(true);
            request.setAllowedOverRoaming(true);
            long downloadId = manager.enqueue(request);
            execute(() -> pollDownload(call, manager, downloadId, target, expectedSha256));
        } catch (Exception ex) {
            call.reject("Failed to start APK download", "DOWNLOAD_START_FAILED", ex);
        }
    }

    @PluginMethod
    public void installApk(PluginCall call) {
        String filePath = call.getString("filePath");
        if (filePath == null || filePath.trim().isEmpty()) {
            call.reject("filePath is required", "BAD_INPUT");
            return;
        }

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O && !getContext().getPackageManager().canRequestPackageInstalls()) {
            JSObject result = new JSObject();
            result.put("needsPermission", true);
            call.resolve(result);
            return;
        }

        try {
            File apk = new File(filePath);
            if (!apk.exists() || !apk.isFile()) {
                call.reject("Downloaded APK not found", "APK_NOT_FOUND");
                return;
            }

            Uri uri = FileProvider.getUriForFile(
                getContext(),
                getContext().getPackageName() + ".fileprovider",
                apk
            );
            Intent intent = new Intent(Intent.ACTION_VIEW);
            intent.setDataAndType(uri, APK_MIME);
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);

            JSObject result = new JSObject();
            result.put("needsPermission", false);
            result.put("started", true);
            call.resolve(result);
        } catch (Exception ex) {
            call.reject("Failed to open Android installer", "INSTALL_FAILED", ex);
        }
    }

    @PluginMethod
    public void openInstallPermissionSettings(PluginCall call) {
        try {
            Intent intent;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                intent = new Intent(
                    Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES,
                    Uri.parse("package:" + getContext().getPackageName())
                );
            } else {
                intent = new Intent(Settings.ACTION_SECURITY_SETTINGS);
            }
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            getContext().startActivity(intent);
            call.resolve();
        } catch (Exception ex) {
            call.reject("Failed to open install permission settings", "SETTINGS_FAILED", ex);
        }
    }

    private void pollDownload(PluginCall call, DownloadManager manager, long downloadId, File target, String expectedSha256) {
        DownloadManager.Query query = new DownloadManager.Query().setFilterById(downloadId);
        try {
            while (true) {
                try (Cursor cursor = manager.query(query)) {
                    if (cursor == null || !cursor.moveToFirst()) {
                        call.reject("APK download disappeared", "DOWNLOAD_MISSING");
                        return;
                    }

                    int status = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_STATUS));
                    long received = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_BYTES_DOWNLOADED_SO_FAR));
                    long total = cursor.getLong(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_TOTAL_SIZE_BYTES));
                    notifyProgress(received, total);

                    if (status == DownloadManager.STATUS_SUCCESSFUL) {
                        verifyDownloadedApk(target, expectedSha256);
                        JSObject result = new JSObject();
                        result.put("filePath", target.getAbsolutePath());
                        result.put("fileName", target.getName());
                        result.put("size", target.length());
                        call.resolve(result);
                        return;
                    }

                    if (status == DownloadManager.STATUS_FAILED) {
                        int reason = cursor.getInt(cursor.getColumnIndexOrThrow(DownloadManager.COLUMN_REASON));
                        if (reason == 429) {
                            call.reject("下载请求过于频繁，请稍后重试。", "RATE_LIMIT");
                        } else {
                            call.reject("APK download failed: " + reason, "DOWNLOAD_FAILED");
                        }
                        return;
                    }
                }
                Thread.sleep(500);
            }
        } catch (Exception ex) {
            call.reject("APK download failed", "DOWNLOAD_FAILED", ex);
        }
    }

    private void notifyProgress(long received, long total) {
        JSObject progress = new JSObject();
        progress.put("receivedBytes", received);
        progress.put("totalBytes", total);
        if (total > 0) {
            progress.put("percent", Math.min(100, Math.max(0, Math.round((received * 100.0f) / total))));
        } else {
            progress.put("percent", 0);
        }
        notifyListeners("downloadProgress", progress);
    }

    private void verifyDownloadedApk(File target, String expectedSha256) throws Exception {
        if (!target.exists() || !target.isFile()) {
            throw new IllegalStateException("Downloaded APK not found");
        }
        if (expectedSha256 == null || expectedSha256.trim().isEmpty()) {
            return;
        }
        String actual = sha256(target);
        if (!actual.equalsIgnoreCase(expectedSha256.trim())) {
            target.delete();
            throw new IllegalStateException("APK SHA-256 mismatch");
        }
    }

    private String sha256(File file) throws Exception {
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        try (InputStream input = new BufferedInputStream(new FileInputStream(file))) {
            byte[] buffer = new byte[1024 * 1024];
            int read;
            while ((read = input.read(buffer)) != -1) {
                digest.update(buffer, 0, read);
            }
        }
        byte[] hash = digest.digest();
        StringBuilder builder = new StringBuilder(hash.length * 2);
        for (byte b : hash) {
            builder.append(String.format(Locale.ROOT, "%02x", b));
        }
        return builder.toString();
    }

    private String sanitizeFileName(String raw) {
        String cleaned = raw == null ? "Lawver.apk" : raw.replaceAll("[\\\\/:*?\"<>|\\x00-\\x1f]", "_").trim();
        if (cleaned.isEmpty() || !cleaned.toLowerCase(Locale.ROOT).endsWith(".apk")) {
            return "Lawver.apk";
        }
        return cleaned;
    }

    private String readAll(InputStream stream) throws Exception {
        try (InputStream input = stream; ByteArrayOutputStream output = new ByteArrayOutputStream()) {
            byte[] buffer = new byte[8192];
            int read;
            while ((read = input.read(buffer)) != -1) {
                output.write(buffer, 0, read);
            }
            return output.toString("UTF-8");
        }
    }
}
