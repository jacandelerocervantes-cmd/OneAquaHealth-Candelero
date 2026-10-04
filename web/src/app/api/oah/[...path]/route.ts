import { handleProxy } from "@/lib/server/proxy";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ path: string[] }> };

export async function GET(request: Request, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  return handleProxy(request, path);
}

export async function POST(request: Request, ctx: Ctx): Promise<Response> {
  const { path } = await ctx.params;
  return handleProxy(request, path);
}
