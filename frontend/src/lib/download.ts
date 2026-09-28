/*
 * 模块描述：跨平台文件下载，Web 使用浏览器下载，原生 Android 使用 FileTransfer + Share。
 */

import { Directory, Filesystem } from "@capacitor/filesystem";
import { FileTransfer } from "@capacitor/file-transfer";
import { Share } from "@capacitor/share";
import { getAuthToken } from "./auth-storage";
import { isNative } from "./platform";
import { apiFetch, apiUrl } from "../services/api";

export const safeDownloadName = (name: string) => {
  const fallback = "lawver-file";
  const base = (name.split("/").pop() || name || fallback)
    .replace(/[\\/:*?"<>|\x00-\x1f]/g, "_")
    .replace(/\s+/g, " ")
    .trim();
  return base || fallback;
};

const downloadPath = (filePath: string) =>
  `/api/download?file_path=${encodeURIComponent(filePath)}`;

const browserDownload = async (filePath: string, fileName: string) => {
  const response = await apiFetch(downloadPath(filePath));
  if (!response.ok) throw new Error("Download failed");
  const blob = await response.blob();
  const href = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = href;
  link.download = fileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(href);
};

const nativeDownload = async (filePath: string, fileName: string) => {
  await Filesystem.mkdir({
    directory: Directory.Cache,
    path: "downloads",
    recursive: true,
  }).catch(() => undefined);

  const targetPath = `downloads/${fileName}`;
  const target = await Filesystem.getUri({
    directory: Directory.Cache,
    path: targetPath,
  });
  const token = await getAuthToken();
  const headers: Record<string, string> = {
    "X-Lawver-Client": "capacitor",
  };
  if (token) headers.Authorization = `Bearer ${token}`;

  await FileTransfer.downloadFile({
    url: apiUrl(downloadPath(filePath)),
    path: target.uri,
    headers,
  });

  const stored = await Filesystem.getUri({
    directory: Directory.Cache,
    path: targetPath,
  });
  await Share.share({
    title: fileName,
    dialogTitle: "打开或分享文件",
    files: [stored.uri],
  });
};

export const downloadWorkspaceFile = async (
  filePath: string,
  name?: string,
) => {
  const fileName = safeDownloadName(name || filePath);
  if (isNative()) {
    await nativeDownload(filePath, fileName);
    return;
  }
  await browserDownload(filePath, fileName);
};

/** Reuse the same authenticated native download/share path for v2 documents. */
export const downloadApiFile = async (path: string, name: string) => {
  if (!path.startsWith("/api/")) throw new Error("Invalid download route");
  const fileName = safeDownloadName(name);
  if (isNative()) {
    await Filesystem.mkdir({
      directory: Directory.Cache,
      path: "downloads",
      recursive: true,
    }).catch(() => undefined);
    const target = await Filesystem.getUri({
      directory: Directory.Cache,
      path: `downloads/${fileName}`,
    });
    const token = await getAuthToken();
    await FileTransfer.downloadFile({
      url: apiUrl(path),
      path: target.uri,
      headers: {
        "X-Lawver-Client": "capacitor",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
    });
    await Share.share({
      title: fileName,
      dialogTitle: "打开或分享文件",
      files: [target.uri],
    });
    return;
  }
  const response = await apiFetch(path);
  if (!response.ok) throw new Error("无法下载文档");
  const href = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = href;
  link.download = fileName;
  link.click();
  setTimeout(() => URL.revokeObjectURL(href), 30000);
};

export const downloadWorkbenchFile = (id: string, name: string, word = false) =>
  downloadApiFile(
    `/api/v2/documents/${encodeURIComponent(id)}/${word ? "export" : "blob"}`,
    name + (word ? ".docx" : ""),
  );
