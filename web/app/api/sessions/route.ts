import { NextResponse } from "next/server";
import { listRuns, listSessions } from "@/lib/trace";

export const dynamic = "force-dynamic";

export async function GET() {
  const [sessions, runs] = await Promise.all([listSessions(), listRuns()]);
  return NextResponse.json({ sessions, runs });
}
