import { NextRequest, NextResponse } from 'next/server'
import { BACKEND_URL } from '@/lib/config'

/**
 * Frontend proxy for uploading a full-text PDF for a citation, extracting stored PDFs,
 * and streaming stored PDFs to the browser for viewing.
 *
 * Routes handled:
 * - POST /api/can-sr/citations/full-text?sr_id=<sr_id>&citation_id=<id>
 *    -> upload multipart/form-data with 'file' to: POST {BACKEND_URL}/api/cite/{sr_id}/citations/{citation_id}/upload-fulltext
 *
 * - POST /api/can-sr/citations/full-text?action=extract&sr_id=<sr_id>&citation_id=<id>
 *    -> trigger backend extraction for stored PDF: POST {BACKEND_URL}/api/extract/{sr_id}/citations/{citation_id}/extract-fulltext
 *
 * - GET  /api/can-sr/citations/full-text?sr_id=<sr_id>&citation_id=<id>
 *    -> stream the stored PDF associated with the citation (calls backend citation endpoint to resolve document_id/storage_path,
 *       then proxies to backend download endpoint or streams the storage URL)
 *
 * - GET  /api/can-sr/citations/full-text?document_id=<document_id>
 *    -> stream the document directly from backend download endpoint:
 *       GET {BACKEND_URL}/api/files/documents/{document_id}/download
 *
 * Authentication: forwards Authorization header for all backend calls (required).
 */

function copyHeaders(src: Headers) {
  const out: Record<string, string> = {}
  src.forEach((value, key) => {
    out[key] = value
  })
  return out
}

export async function OPTIONS() {
  // Respond to CORS preflight requests (browsers send OPTIONS when Authorization header is present)
  return new Response(null, {
    status: 204,
    headers: {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET,POST,OPTIONS',
      'Access-Control-Allow-Headers': 'Authorization, Content-Type',
    },
  })
}

export async function GET(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const citationId = params.get('citation_id')
    const documentIdParam = params.get('document_id')

    const authHeader = request.headers.get('authorization')
    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }

    let fileFetchUrl: string | null = null
    const fetchOptions: Record<string, any> = {
      method: 'GET',
      headers: {
        Authorization: authHeader,
      },
    }

    if (documentIdParam) {
      // Prefer direct document_id -> backend files download route
      fileFetchUrl = `${BACKEND_URL}/api/files/documents/${encodeURIComponent(
        documentIdParam,
      )}/download`
    } else if (srId && citationId) {
      // Fetch the citation row to locate document_id or storage_path
      const citationUrl = `${BACKEND_URL}/api/cite/${encodeURIComponent(
        srId,
      )}/citations/${encodeURIComponent(citationId)}`

      const citationRes = await fetch(citationUrl, {
        method: 'GET',
        headers: {
          Authorization: authHeader,
        },
      })

      if (!citationRes.ok) {
        const json = await citationRes.json().catch(() => ({}))
        return NextResponse.json(
          { error: json?.error || json?.detail || 'Failed to load citation' },
          { status: citationRes.status },
        )
      }

      const citation = await citationRes.json().catch(() => ({}))
      // Try common fields: document_id, documentId, storage_path, fulltext_url
      const documentId =
        citation?.document_id || citation?.documentId || citation?.document || null
      const storagePath =
        citation?.storage_path || citation?.storagePath || citation?.fulltext_url || citation?.fulltext || null

      if (documentId) {
        fileFetchUrl = `${BACKEND_URL}/api/files/documents/${encodeURIComponent(
          documentId,
        )}/download`
      } else if (storagePath) {
        // If storage_path looks like a full URL (contains scheme) fetch it directly.
        // Otherwise treat it as a storage key ("container/blob") and proxy via backend.
        if (storagePath.includes('://')) {
          fileFetchUrl = storagePath
        } else {
          // Call backend helper to stream blobs by storage path
          fileFetchUrl = `${BACKEND_URL}/api/files/download-by-path?path=${encodeURIComponent(
            storagePath,
          )}`
        }
      } else {
        return NextResponse.json(
          { error: 'No document_id or storage_path found for citation' },
          { status: 404 },
        )
      }
    } else {
      return NextResponse.json(
        { error: 'document_id or sr_id+citation_id are required' },
        { status: 400 },
      )
    }

    // Fetch the file (stream)
    const backendRes = await fetch(fileFetchUrl!, {
      method: 'GET',
      headers: fetchOptions.headers,
    })

    if (!backendRes.ok) {
      // Try to surface backend JSON error if present
      const text = await backendRes.text().catch(() => null)
      let msg = text
      try {
        const json = text ? JSON.parse(text) : null
        msg = json?.detail || json?.error || text
      } catch {
        // ignore parse errors
      }
      return NextResponse.json(
        { error: msg || 'Failed to download document' },
        { status: backendRes.status },
      )
    }

    // Stream response back to client preserving content headers
    const headers = copyHeaders(backendRes.headers)

    // Ensure content-type defaults to application/pdf if not set
    if (!headers['content-type']) {
      headers['content-type'] = 'application/pdf'
    }

    return new Response(backendRes.body, {
      status: backendRes.status,
      headers,
    })
  } catch (err: any) {
    console.error('Fulltext proxy GET error:', err)
    return NextResponse.json({ error: 'Internal server error' }, { status: 500 })
  }
}

export async function POST(request: NextRequest) {
  try {
    const params = request.nextUrl.searchParams
    const srId = params.get('sr_id')
    const citationId = params.get('citation_id')
    const action = params.get('action') // optional; if 'extract' will call backend extract endpoint

    if (!srId || !citationId) {
      return NextResponse.json(
        { error: 'sr_id and citation_id are required' },
        { status: 400 },
      )
    }

    const authHeader = request.headers.get('authorization')

    // If action=extract, call backend extract endpoint which will download PDF from storage and run Grobid
    if (action === 'extract') {
      const url = `${BACKEND_URL}/api/extract/${encodeURIComponent(
        srId,
      )}/citations/${encodeURIComponent(citationId)}/extract-fulltext`

      if (!authHeader) {
        return NextResponse.json(
          { error: 'Authorization header is required' },
          { status: 401 },
        )
      }

      const res = await fetch(url, {
        method: 'POST',
        headers: {
          Authorization: authHeader,
        },
      })

      const data = await res.json().catch(() => ({}))
      return NextResponse.json(data, { status: res.status })
    }

    // Otherwise assume this is an upload of a PDF file (multipart/form-data)
    const formData = await request.formData()
    const file = formData.get('file') as File

    if (!file || !file.name) {
      return NextResponse.json({ error: 'File is required' }, { status: 400 })
    }

    // Basic validation: only allow PDFs (backend enforces this too)
    if (!file.name.toLowerCase().endsWith('.pdf')) {
      return NextResponse.json(
        { error: 'Only PDF files are accepted for full text upload' },
        { status: 400 },
      )
    }

    // Forward form data to backend upload endpoint
    const backendForm = new FormData()
    backendForm.append('file', file)

    const url = `${BACKEND_URL}/api/cite/${encodeURIComponent(
      srId,
    )}/citations/${encodeURIComponent(citationId)}/upload-fulltext`

    if (!authHeader) {
      return NextResponse.json(
        { error: 'Authorization header is required' },
        { status: 401 },
      )
    }

    const res = await fetch(url, {
      method: 'POST',
      headers: {
        Authorization: authHeader,
      },
      body: backendForm as any,
    })

    const data = await res.json().catch(() => ({}))
    if (!res.ok) {
      return NextResponse.json(
        { error: data.detail || data || 'Upload failed' },
        { status: res.status },
      )
    }

    return NextResponse.json(data, { status: res.status })
  } catch (error) {
    console.error('Citations full-text POST API error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 },
    )
  }
}
