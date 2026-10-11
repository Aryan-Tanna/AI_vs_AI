import { NextRequest, NextResponse } from "next/server";
import { readTrace, safeId } from "@/lib/trace";

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id } = await ctx.params;
  if (!safeId(id)) return NextResponse.json({ error: "bad id" }, { status: 400 });
  const after = Number(req.nextUrl.searchParams.get("after") ?? "-1");
  try {
    const recs = await readTrace(id);
    return NextResponse.json({ records: recs.filter((r) => r.seq > after) });
  } catch {
    return NextResponse.json({ error: "no such session" }, { status: 404 });
  }
}
