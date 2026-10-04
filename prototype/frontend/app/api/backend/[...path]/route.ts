import { NextRequest, NextResponse } from 'next/server';

const allowedGetPaths = [
  /^\/health$/,
  /^\/customers$/,
  /^\/customers\/[A-Za-z0-9_-]+$/,
  /^\/purposes$/,
  /^\/api\/v1\/sandbox$/,
  /^\/api\/v1\/sandbox\/events$/,
  /^\/api\/v1\/ingest\/health$/,
  /^\/investigations$/,
  /^\/investigations\/[A-Za-z0-9_-]+$/,
  /^\/investigations\/[A-Za-z0-9_-]+\/graph$/,
  /^\/investigations\/[A-Za-z0-9_-]+\/evidence\/[A-Za-z0-9_-]+$/,
];

const allowedPostPaths = [
  /^\/investigations\/withdrawal$/,
  /^\/investigations\/remediation$/,
  /^\/investigations\/reinvestigate$/,
  /^\/api\/v1\/sandbox\/reset$/,
  /^\/api\/v1\/sandbox\/scenarios\/[A-Za-z0-9-]+\/run$/,
];

async function proxy(request: NextRequest, segments: string[]) {
  const mode = (process.env.APP_MODE || 'SANDBOX').toUpperCase();
  const backendUrl = process.env.CONSENTTRACE_BACKEND_URL;
  const path = `/${segments.map((segment) => encodeURIComponent(segment)).join('/')}`;
  const methodPaths = request.method === 'GET' ? allowedGetPaths : allowedPostPaths;

  if (!['DEMO', 'SANDBOX'].includes(mode) || !backendUrl) {
    return NextResponse.json({ error: { code: 'NOT_AVAILABLE', message: 'The local development API proxy is unavailable.' } }, { status: 404 });
  }
  if (!methodPaths.some((pattern) => pattern.test(path))) {
    return NextResponse.json({ error: { code: 'NOT_FOUND', message: 'This API route is not exposed by the local development proxy.' } }, { status: 404 });
  }

  const requestBody = request.method === 'GET' ? undefined : await request.arrayBuffer();
  let requestedOrganization = '';
  if (requestBody && request.headers.get('content-type')?.includes('application/json')) {
    try {
      const document = JSON.parse(new TextDecoder().decode(requestBody)) as { organization_id?: string; investigation_id?: string };
      requestedOrganization = document.organization_id || '';
      if (document.investigation_id?.startsWith('INV-org-democorp-sandbox-')) {
        requestedOrganization = 'org-democorp-sandbox';
      }
    } catch {
      return NextResponse.json({ error: { code: 'INVALID_REQUEST', message: 'The request body must be valid JSON.' } }, { status: 400 });
    }
  }
  const sandboxRequest = path.startsWith('/api/v1/sandbox')
    || requestedOrganization === 'org-democorp-sandbox'
    || path.includes('/INV-org-democorp-sandbox-');
  const apiKey = sandboxRequest
    ? process.env.CONSENTTRACE_SANDBOX_API_KEY
    : process.env.CONSENTTRACE_DEV_API_KEY;
  if (!apiKey) {
    return NextResponse.json({ error: { code: 'NOT_AVAILABLE', message: 'The local development API proxy is unavailable.' } }, { status: 404 });
  }
  const requestId = request.headers.get('x-request-id');
  const headers = new Headers({
    Authorization: `Bearer ${apiKey}`,
    Accept: 'application/json',
  });
  if (request.headers.get('content-type')) headers.set('Content-Type', request.headers.get('content-type')!);
  if (requestId && /^[A-Za-z0-9._:-]{1,128}$/.test(requestId)) headers.set('X-Request-ID', requestId);

  try {
    const response = await fetch(`${backendUrl.replace(/\/+$/, '')}${path}${request.nextUrl.search}`, {
      method: request.method,
      headers,
      body: requestBody,
      cache: 'no-store',
      redirect: 'manual',
    });
    const responseHeaders = new Headers();
    const contentType = response.headers.get('content-type');
    const responseRequestId = response.headers.get('x-request-id');
    if (contentType) responseHeaders.set('Content-Type', contentType);
    if (responseRequestId) responseHeaders.set('X-Request-ID', responseRequestId);
    return new NextResponse(response.body, { status: response.status, headers: responseHeaders });
  } catch {
    return NextResponse.json({ error: { code: 'UPSTREAM_UNAVAILABLE', message: 'The development API could not be reached.' } }, { status: 502 });
  }
}

type RouteContext = { params: { path: string[] } };

export async function GET(request: NextRequest, context: RouteContext) {
  return proxy(request, context.params.path);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return proxy(request, context.params.path);
}
