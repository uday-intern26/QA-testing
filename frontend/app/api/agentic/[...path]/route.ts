import { NextRequest, NextResponse } from "next/server";

export const runtime = "nodejs";

const upstream = process.env.AGENTIC_QA_API_URL || process.env.QA_API_URL || "http://127.0.0.1:8001";

type Context = { params: { path: string[] } };

async function forward(request: NextRequest, path: string[]) {
  const target = new URL(`/${path.join("/")}`, upstream);
  target.search = request.nextUrl.search;
  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const init: RequestInit = { method: request.method, headers };
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
  } catch {
    return NextResponse.json(
      {
        detail: `Agentic QA API is not reachable at ${upstream}. Start it with: uvicorn app.main:app --host 127.0.0.1 --port 8001`,
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
