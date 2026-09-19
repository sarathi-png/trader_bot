import { NextRequest, NextResponse } from 'next/server';

export async function GET(request: NextRequest) {
  const wsUrl = `ws://localhost:${process.env.WEBSOCKET_PORT || '8765'}`;

  try {
    const ws = new WebSocket(wsUrl);
    return new NextResponse(JSON.stringify({ status: 'connected', wsUrl }), {
      headers: { 'Content-Type': 'application/json' },
    });
  } catch {
    return NextResponse.json({ status: 'disconnected' }, { status: 503 });
  }
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    return NextResponse.json({ received: true, data: body });
  } catch {
    return NextResponse.json({ error: 'Invalid body' }, { status: 400 });
  }
}
