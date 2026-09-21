/*
 * Cloudflare Worker 区域路径分流示例。
 *
 * 按路径前缀把请求转发到不同区域后端，并为 HTML 静态注入 <base>。
 *
 * 路径前缀会自动移除：
 *
 *   /cn/api/chat    -> https://cn-origin.example.com/api/chat
 *   /asean/api/chat -> https://asean-origin.example.com/api/chat
 *
 * 为什么必须注入 <base>：
 * 应用产物用相对路径引用资源（./assets/index-xxx.js），浏览器按 <base> 解析。
 * <base> 必须是 HTML 流里的静态标签；若改由前端脚本运行时插入，会晚于浏览器的
 * 预加载扫描器——扫描器会用去掉尾斜杠的目录（/cn → /）作基准，把 ./assets/...
 * 请求成 /assets/...，这些请求命中下方 "/" 默认路由，导致 /asean 页面加载到
 * cn 区域的静态资源。因此注入点必须放在网关这一层。
 *
 * 前缀列表需与 package.json 的 appConfig.regions 保持一致：
 * 应用侧在网关未注入 <base> 时按该列表兜底识别前缀。
 */

const ROUTES = [
  {
    path: "/cn",
    origin: "https://cn-origin.lawver.dev",
  },
  {
    path: "/asean",
    origin: "https://asean-origin.lawver.dev",
  },
  // "/" 表示默认 Origin
  {
    path: "/",
    origin: "https://cn-origin.lawver.dev",
  },
];

function matchRoute(pathname) {
  // 最长路径优先
  const routes = [...ROUTES].sort((a, b) => b.path.length - a.path.length);

  for (const route of routes) {
    if (route.path === "/") {
      return route;
    }

    if (pathname === route.path || pathname.startsWith(route.path + "/")) {
      return route;
    }
  }

  return null;
}

function joinPath(base, path) {
  const left = base === "/" ? "" : base.replace(/\/+$/, "");
  const right = path.startsWith("/") ? path : "/" + path;
  return left + right || "/";
}

/** 为带前缀的 HTML 响应注入静态 <base>，位置在 head 开头、所有资源标签之前。 */
function injectBasePath(response, prefix) {
  const contentType = response.headers.get("content-type") || "";
  if (!prefix || !contentType.includes("text/html")) {
    return response;
  }

  return new HTMLRewriter()
    .on("head", {
      element(element) {
        element.prepend(`<base href="${prefix}/">`, { html: true });
      },
    })
    .transform(response);
}

export default {
  async fetch(request) {
    const incoming = new URL(request.url);
    const route = matchRoute(incoming.pathname);

    if (!route) {
      return new Response("No route matched", { status: 404 });
    }

    const upstream = new URL(route.origin);

    // 默认 "/" 路由保留完整路径；带前缀的路由先移除前缀再转发。
    if (route.path === "/") {
      upstream.pathname = joinPath(upstream.pathname, incoming.pathname);
    } else {
      const remaining = incoming.pathname.slice(route.path.length) || "/";
      upstream.pathname = joinPath(upstream.pathname, remaining);
    }

    upstream.search = incoming.search;

    try {
      const upstreamRequest = new Request(upstream.toString(), request);
      const response = await fetch(upstreamRequest);
      const prefix = route.path === "/" ? "" : route.path;

      const headers = new Headers(response.headers);
      headers.set("X-Worker-Origin", upstream.origin);
      headers.set("X-Worker-Path", upstream.pathname);

      const body = injectBasePath(
        new Response(response.body, {
          status: response.status,
          statusText: response.statusText,
          headers,
        }),
        prefix,
      );

      // 注入改变了响应体长度，交由平台重新计算
      const finalHeaders = new Headers(body.headers);
      finalHeaders.delete("content-length");

      return new Response(body.body, {
        status: body.status,
        statusText: body.statusText,
        headers: finalHeaders,
      });
    } catch (error) {
      return new Response(
        JSON.stringify(
          {
            error: String(error),
            target: upstream.toString(),
            matchedRoute: route.path,
          },
          null,
          2,
        ),
        {
          status: 502,
          headers: {
            "Content-Type": "application/json; charset=utf-8",
          },
        },
      );
    }
  },
};
