import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";
/** Validate opens a browser and can take several minutes. */
export const maxDuration = 300;

const upstream =
  process.env.TRYON_QA_API_URL ||
  process.env.QA_API_INTERNAL_URL ||
  "http://127.0.0.1:8001";

type Context = { params: { path: string[] } };

async function forward(request: NextRequest, path: string[]) {
  const target = new URL(`/api/v1/${path.join("/")}`, upstream.replace(/\/$/, "") + "/");
  target.search = request.nextUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers,
    // Do not set a short AbortSignal — try-on validate is intentionally slow.
    cache: "no-store",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }
  try {
    const response = await fetch(target, init);
    const body = await response.arrayBuffer();
    const out = new Headers();
    const type = response.headers.get("content-type");
    if (type) out.set("content-type", type);
    return new NextResponse(body, { status: response.status, headers: out });
  } catch (exc) {
    const reason = exc instanceof Error ? exc.message : "upstream unreachable";
    return NextResponse.json(
      {
        detail: {
          code: "UPSTREAM_UNREACHABLE",
          message: `Try-On QA API at ${upstream} did not respond (${reason}).`,
          recommended_action: "Start the API with: uvicorn app.main:app --host 127.0.0.1 --port 8001",
        },
      },
      { status: 502 },
    );
  }
}

export async function GET(request: NextRequest, context: Context) {
  return forward(request, context.params.path);
}

export async function POST(request: NextRequest, context: Context) {
  return forward(request, context.params.path);
}

export async function PUT(request: NextRequest, context: Context) {
  return forward(request, context.params.path);
}

export async function PATCH(request: NextRequest, context: Context) {
  return forward(request, context.params.path);
}

export async function DELETE(request: NextRequest, context: Context) {
  return forward(request, context.params.path);
}
