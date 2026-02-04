import { useState, useEffect, useRef, forwardRef, useImperativeHandle } from 'react'
import { getAuthToken, getTokenType } from '@/lib/auth'
import { useDictionary } from '@/app/[lang]/DictionaryProvider'

interface PDFBoundingBoxViewerProps {
  srId: string
  citationId: string | number
  conversionId?: string | null
  fileName?: string
  // GROBID sentence-level coordinates and page sizes
  coords?: any[]
  pages?: { width: number; height: number }[]
  // AI evidence and toggle state from sidebar
  aiPanels?: Record<string, any>
  panelOpen?: Record<string, boolean>
  // Numbered fulltext string "[0] ...\n\n[1] ...", for mapping indices->text
  fulltext?: string
  // Start with fit-to-width enabled
  defaultFitToWidth?: boolean
}

/**
 * PDFBoundingBoxViewer
 * - Renders all pages stacked vertically using pdf.js
 * - Draws an overlay of sentence boxes from GROBID coords
 * - Highlight filtering:
 *    • If "Show Bounding Boxes" checkbox is on: draw all sentence boxes
 *    • Otherwise: draw only sentences referenced by any parameter panel that is currently open
 * - Coloring: per-parameter deterministic color based on parameter name
 */

const COLOR_MAP: Record<string, string> = {
  paragraphs: 'rgba(128, 0, 128, 0.3)',
  tables: 'rgba(255, 128, 0, 0.4)',
  table_cells: 'rgba(255, 179, 77, 0.2)',
  figures: 'rgba(0, 204, 0, 0.4)',
  title: 'rgba(204, 0, 0, 0.4)',
  section_heading: 'rgba(153, 0, 102, 0.4)',
}

const COLOR_BORDER_MAP: Record<string, string> = {
  paragraphs: 'rgb(128, 0, 128)',
  tables: 'rgb(255, 128, 0)',
  table_cells: 'rgb(255, 179, 77)',
  figures: 'rgb(0, 204, 0)',
  title: 'rgb(204, 0, 0)',
  section_heading: 'rgb(153, 0, 102)',
}

function hashCode(str: string): number {
  let hash = 0
  for (let i = 0; i < str.length; i++) {
    hash = (hash << 5) - hash + str.charCodeAt(i)
    hash |= 0
  }
  return Math.abs(hash)
}

function colorForParam(param: string, alpha = 0.35): string {
  const h = hashCode(param) % 360
  const s = 50 + hashCode(param) % 50
  const l = 40 + hashCode(param) % 20
  return `hsla(${h}, ${s}%, ${l}%, ${alpha})`
}

function solidForParam(param: string): string {
  const h = hashCode(param) % 360
  const s = 50 + hashCode(param) % 50
  const l = 40 + hashCode(param) % 20
  return `hsl(${h}, ${s}%, ${l}%)`
}

function extractSentenceArray(fulltext?: string): string[] {
  if (!fulltext || typeof fulltext !== 'string') return []
  const lines = fulltext.split(/\n+/).map((s) => s.trim()).filter(Boolean)
  const out: string[] = []
  for (const line of lines) {
    const m = line.match(/^\[(\d+)\]\s*(.*)$/)
    if (m) {
      const idx = parseInt(m[1], 10)
      out[idx] = m[2]
    }
  }
  // fill holes if any
  return out.filter((v) => typeof v === 'string')
}

export type PDFBoundingBoxViewerHandle = {
  scrollToPage: (pageNum: number) => void
  scrollToCoord: (coord: any) => void
  scrollToSentenceIndex: (idx: number) => void
}

const PDFBoundingBoxViewer = forwardRef<PDFBoundingBoxViewerHandle, PDFBoundingBoxViewerProps>(function PDFBoundingBoxViewer(
  {
    srId,
    citationId,
    conversionId = null,
    fileName,
    coords = [],
    pages = [],
    aiPanels = {},
    panelOpen = {},
    fulltext,
    defaultFitToWidth = true,
  }: PDFBoundingBoxViewerProps,
  ref
) {
  const dict = useDictionary()
  const [pdfUrl, setPdfUrl] = useState<string | null>(null)
  const [analysisResult, setAnalysisResult] = useState<any | null>(null)
  const [currentPage, setCurrentPage] = useState(1)
  const [totalPages, setTotalPages] = useState(0)
  const [scale, setScale] = useState(1.0)
  const [fitToWidth, setFitToWidth] = useState(!!defaultFitToWidth)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
const pageRefs = useRef<{ [key: number]: HTMLCanvasElement | null }>({})
const containerRef = useRef<HTMLDivElement | null>(null)
const wrapperRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const [pdfDocument, setPdfDocument] = useState<any | null>(null)
  const [showBoundingBoxes, setShowBoundingBoxes] = useState(true)
  const [visibleElements, setVisibleElements] = useState<Set<string>>(new Set(['paragraphs', 'tables', 'figures']))
  const [pageViewports, setPageViewports] = useState<Record<number, { width: number; height: number }>>({})
  const renderTasksRef = useRef<Record<number, any>>({})
  const renderTokenRef = useRef(0)
  const [hoverInfo, setHoverInfo] = useState<{ page: number; left: number; top: number; content: string } | null>(null)

const sentenceTexts = extractSentenceArray(fulltext)

useImperativeHandle(ref, () => ({
  scrollToPage: (pageNum: number) => {
    const container = containerRef.current
    const wrapper = wrapperRefs.current[pageNum]
    if (container && wrapper) {
      const top = wrapper.offsetTop - 12
      container.scrollTo({ top, behavior: 'smooth' })
      setCurrentPage(Math.min(Math.max(1, pageNum), totalPages || pageNum))
    }
  },
  scrollToCoord: (coord: any) => {
    try {
      const pageNum = Number(coord?.page ?? coord?.page_number ?? coord?.pageNum ?? 1)
      const vp = pageViewports[pageNum]
      const dims = pages?.[pageNum - 1]
      const container = containerRef.current
      const wrapper = wrapperRefs.current[pageNum]
      if (!vp || !dims || !container || !wrapper) return
      const pageWidth = Number(dims.width || 1)
      const pageHeight = Number(dims.height || 1)
      const ulx = parseFloat(coord?.ulx ?? coord?.x ?? 0)
      const uly = parseFloat(coord?.uly ?? coord?.y ?? 0)
      const lrx = coord?.lrx != null ? parseFloat(coord.lrx) : (coord?.width != null ? ulx + parseFloat(coord.width) : ulx)
      const lry = coord?.lry != null ? parseFloat(coord.lry) : (coord?.height != null ? uly + parseFloat(coord.height) : uly)
      const topY = Math.min(uly, lry)
      const topLocal = Math.max((topY / pageHeight) * vp.height, 0)
      setShowBoundingBoxes(true)
      const top = wrapper.offsetTop + topLocal - 24
      container.scrollTo({ top, behavior: 'smooth' })
      setCurrentPage(Math.min(Math.max(1, pageNum), totalPages || pageNum))
    } catch {}
  },
  scrollToSentenceIndex: (idx: number) => {
    try {
      const t = sentenceTexts && sentenceTexts[idx]
      if (!t) return
      const trimmed = String(t).trim()
      const firstCoord =
        Array.isArray(coords) ? coords.find((c: any) => String(c?.text || '').trim() === trimmed) : null
      if (!firstCoord) return
      const pageNum = Number(firstCoord?.page ?? firstCoord?.page_number ?? firstCoord?.pageNum ?? 1)
      const vp = pageViewports[pageNum]
      const dims = pages?.[pageNum - 1]
      const container = containerRef.current
      const wrapper = wrapperRefs.current[pageNum]
      if (!vp || !dims || !container || !wrapper) return
      const pageHeight = Number(dims.height || 1)
      const ulx = parseFloat(firstCoord?.ulx ?? firstCoord?.x ?? 0)
      const uly = parseFloat(firstCoord?.uly ?? firstCoord?.y ?? 0)
      const lrx = firstCoord?.lrx != null ? parseFloat(firstCoord.lrx) : (firstCoord?.width != null ? ulx + parseFloat(firstCoord.width) : ulx)
      const lry = firstCoord?.lry != null ? parseFloat(firstCoord.lry) : (firstCoord?.height != null ? uly + parseFloat(firstCoord.height) : uly)
      const topY = Math.min(uly, lry)
      const topLocal = Math.max((topY / pageHeight) * vp.height, 0)
      setShowBoundingBoxes(true)
      const top = wrapper.offsetTop + topLocal - 24
      container.scrollTo({ top, behavior: 'smooth' })
      setCurrentPage(Math.min(Math.max(1, pageNum), totalPages || pageNum))
    } catch {}
  }
}), [pageViewports, pages, totalPages, sentenceTexts, coords])

  // Load PDF.js dynamically (CDN)
  useEffect(() => {
    const loadPDFJS = async () => {
      try {
        // @ts-ignore
        if (!window.pdfjsLib) {
          const script = document.createElement('script')
          script.src = 'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.min.js'
          script.async = true
          document.body.appendChild(script)

          await new Promise((resolve, reject) => {
            // @ts-ignore
            script.onload = resolve
            // @ts-ignore
            script.onerror = reject
          })

          // @ts-ignore
          window.pdfjsLib.GlobalWorkerOptions.workerSrc =
            'https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js'
        }
      } catch (err) {
        console.error('Failed to load PDF.js:', err)
        setError('Failed to load PDF viewer library')
      }
    }

    loadPDFJS()
  }, [])

  // Fetch PDF using the frontend proxy
  useEffect(() => {
    const fetchPDF = async () => {
      try {
        const token = getAuthToken()
        const tokenType = getTokenType()
        const headers: Record<string, string> = {}
        if (token) headers['Authorization'] = `${tokenType} ${token}`

        const url = `/api/can-sr/citations/full-text?sr_id=${encodeURIComponent(String(srId))}&citation_id=${encodeURIComponent(
          String(citationId),
        )}`

        const res = await fetch(url, { headers })
        if (!res.ok) {
          throw new Error(`Failed to fetch PDF (${res.status})`)
        }
        const blob = await res.blob()
        const objectUrl = URL.createObjectURL(blob)
        setPdfUrl(objectUrl)
      } catch (err: any) {
        console.error('Error fetching PDF:', err)
        setError(err?.message || 'Failed to load PDF')
      } finally {
        setLoading(false)
      }
    }

    fetchPDF()
    return () => {
      if (pdfUrl) {
        URL.revokeObjectURL(pdfUrl)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [srId, citationId])

  // Fetch analysis result (docling/doc-intelligence) if conversionId provided (optional)
  useEffect(() => {
    const fetchAnalysis = async () => {
      if (!conversionId) return
      try {
        const token = getAuthToken()
        const tokenType = getTokenType()
        const headers: Record<string, string> = {}
        if (token) headers['Authorization'] = `${tokenType} ${token}`
        const res = await fetch(`/api/documents/${encodeURIComponent(conversionId)}/analysis`, { headers })
        if (!res.ok) return
        const data = await res.json()
        setAnalysisResult(data.analysis_result || data)
      } catch (err) {
        console.error('Error fetching analysis:', err)
      }
    }
    fetchAnalysis()
  }, [conversionId])

  // Load PDF document via pdf.js
  useEffect(() => {
    const loadPDF = async () => {
      // @ts-ignore
      if (!pdfUrl || !window.pdfjsLib) return
      try {
        // @ts-ignore
        const loadingTask = window.pdfjsLib.getDocument(pdfUrl)
        const pdf = await loadingTask.promise
        setPdfDocument(pdf)
        setTotalPages(pdf.numPages || 0)
      } catch (err) {
        console.error('Error loading PDF:', err)
        setError('Failed to load PDF document')
      }
    }
    loadPDF()
  }, [pdfUrl])

  // Fit-to-width calculation (use first page to compute scale)
  useEffect(() => {
    const calculateFitToWidth = async () => {
      if (!pdfDocument || !containerRef.current || !fitToWidth) return
      try {
        const page = await pdfDocument.getPage(1)
        const viewport = page.getViewport({ scale: 1.0 })
        const containerWidth = containerRef.current.clientWidth - 64
        const calculatedScale = containerWidth / viewport.width
        setScale(calculatedScale)
      } catch (err) {
        console.error('Error calculating fit to width:', err)
      }
    }
    calculateFitToWidth()
  }, [pdfDocument, fitToWidth])

  // Render all pages into canvases and capture viewport sizes
  useEffect(() => {
    const token = ++renderTokenRef.current
    let cancelled = false

    const renderAllPages = async () => {
      if (!pdfDocument || totalPages === 0) return
      const dpr = window.devicePixelRatio || 1

      for (let pageNum = 1; pageNum <= totalPages; pageNum++) {
        if (cancelled || token !== renderTokenRef.current) break
        const canvas = pageRefs.current[pageNum]
        if (!canvas) continue

        try {
          const page = await pdfDocument.getPage(pageNum)
          if (cancelled || token !== renderTokenRef.current) break
          const viewport = page.getViewport({ scale })
          const context = canvas.getContext('2d')
          if (!context) continue

          // cancel any in-flight render for this page
          const prevTask = renderTasksRef.current[pageNum]
          if (prevTask && typeof prevTask.cancel === 'function') {
            prevTask.cancel()
          }

          // reset transform and clear previous content
          context.setTransform(1, 0, 0, 1, 0, 0)
          context.clearRect(0, 0, canvas.width, canvas.height)

          canvas.style.width = `${viewport.width}px`
          canvas.style.height = `${viewport.height}px`
          canvas.width = Math.floor(viewport.width * dpr)
          canvas.height = Math.floor(viewport.height * dpr)
          context.setTransform(dpr, 0, 0, dpr, 0, 0)

          // track viewport sizes for overlay
          setPageViewports((prev) => {
            const cur = prev[pageNum]
            if (cur && cur.width === viewport.width && cur.height === viewport.height) return prev
            return { ...prev, [pageNum]: { width: viewport.width, height: viewport.height } }
          })

          const task = page.render({ canvasContext: context, viewport })
          renderTasksRef.current[pageNum] = task
          await task.promise.catch((err: any) => {
            if (err?.name !== 'RenderingCancelledException') throw err
          })

          // ensure page resources cleaned up
          try {
            // @ts-ignore
            page.cleanup && page.cleanup()
          } catch {}

          renderTasksRef.current[pageNum] = null

          if (cancelled || token !== renderTokenRef.current) break

        } catch (err: any) {
          if (err?.name !== 'RenderingCancelledException') {
            console.error(`Error rendering page ${pageNum}:`, err)
          }
        }
      }
    }

    renderAllPages()
    return () => {
      cancelled = true
      // cancel all in-flight tasks
      const tasks = renderTasksRef.current
      Object.keys(tasks).forEach((k) => {
        const t = tasks[Number(k)]
        if (t && typeof t.cancel === 'function') t.cancel()
      })
      renderTasksRef.current = {}
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pdfDocument, totalPages, scale])

  const drawDocAnalysisBoundingBoxes = (context: CanvasRenderingContext2D, pageNum: number, pageHeight: number) => {
    if (!analysisResult) return
    const processor = analysisResult.processor || 'unknown'
    const needsYFlip = processor === 'docling'
    const polygonToRect = (polygon: number[], pageHeight: number) => {
      if (!polygon || polygon.length < 8) return null
      const xCoords = polygon.filter((_, i) => i % 2 === 0).map((x) => x * scale)
      const yCoords = polygon
        .filter((_, i) => i % 2 === 1)
        .map((y) => (needsYFlip ? pageHeight - y : y) * scale)
      const x = Math.min(...xCoords)
      const y = Math.min(...yCoords)
      const width = Math.max(...xCoords) - x
      const height = Math.max(...yCoords) - y
      return { x, y, width, height }
    }

    const pageInfo = analysisResult.pages?.find((p: any) => p.page_number === pageNum)
    const ph = pageInfo?.height || pageHeight || 792


    // paragraphs
    if (visibleElements.has('paragraphs') && analysisResult.paragraphs) {
      analysisResult.paragraphs.forEach((para: any) => {
        para.bounding_regions?.forEach((region: any) => {
          if (region.page_number === pageNum) {
            const rect = polygonToRect(region.polygon, ph)
            if (rect) {
              const colorKey = para.role || 'paragraphs'
              context.strokeStyle = COLOR_BORDER_MAP[colorKey] || COLOR_BORDER_MAP.paragraphs
              context.fillStyle = COLOR_MAP[colorKey] || COLOR_MAP.paragraphs
              context.lineWidth = 2
              context.fillRect(rect.x, rect.y, rect.width, rect.height)
              context.strokeRect(rect.x, rect.y, rect.width, rect.height)
              if (para.role) {
                context.fillStyle = COLOR_BORDER_MAP[colorKey] || COLOR_BORDER_MAP.paragraphs
                context.font = '12px sans-serif'
                context.fillText(para.role, rect.x + 2, rect.y - 4)
              }
            }
          }
        })
      })
    }

    // tables
    if (visibleElements.has('tables') && analysisResult.tables) {
      analysisResult.tables.forEach((table: any, idx: number) => {
        table.bounding_regions?.forEach((region: any) => {
          if (region.page_number === pageNum) {
            const rect = polygonToRect(region.polygon, ph)
            if (rect) {
              context.strokeStyle = COLOR_BORDER_MAP.tables
              context.fillStyle = COLOR_MAP.tables
              context.lineWidth = 3
              context.fillRect(rect.x, rect.y, rect.width, rect.height)
              context.strokeRect(rect.x, rect.y, rect.width, rect.height)
              context.fillStyle = COLOR_BORDER_MAP.tables
              context.font = 'bold 14px sans-serif'
              context.fillText(`Table ${idx + 1}`, rect.x + 4, rect.y + 18)
            }
          }
        })
      })
    }

    // figures
    if (visibleElements.has('figures') && analysisResult.figures) {
      analysisResult.figures.forEach((figure: any) => {
        figure.bounding_regions?.forEach((region: any) => {
          if (region.page_number === pageNum) {
            const rect = polygonToRect(region.polygon, ph)
            if (rect) {
              context.strokeStyle = COLOR_BORDER_MAP.figures
              context.fillStyle = COLOR_MAP.figures
              context.lineWidth = 3
              context.fillRect(rect.x, rect.y, rect.width, rect.height)
              context.strokeRect(rect.x, rect.y, rect.width, rect.height)
              context.fillStyle = COLOR_BORDER_MAP.figures
              context.font = 'bold 14px sans-serif'
              context.fillText(`Fig ${figure.id}`, rect.x + 4, rect.y + 18)
            }
          }
        })
      })
    }
  }

  const toggleElement = (element: string) => {
    const newSet = new Set(visibleElements)
    if (newSet.has(element)) newSet.delete(element)
    else newSet.add(element)
    setVisibleElements(newSet)
  }

  // keyboard navigation
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement || e.target instanceof HTMLTextAreaElement) return
      if (e.key === 'ArrowLeft' || e.key === 'PageUp') {
        e.preventDefault()
        setCurrentPage((prev) => Math.max(1, prev - 1))
      } else if (e.key === 'ArrowRight' || e.key === 'PageDown') {
        e.preventDefault()
        setCurrentPage((prev) => Math.min(totalPages, prev + 1))
      } else if (e.key === 'Home') {
        e.preventDefault()
        setCurrentPage(1)
      } else if (e.key === 'End') {
        e.preventDefault()
        setCurrentPage(totalPages)
      }
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [totalPages])

  // Scroll selected page into view when currentPage changes
  useEffect(() => {
    const el = pageRefs.current[currentPage]
    if (!el) return
    el.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [currentPage, totalPages])

  // Build inverted map text -> params for active parameters' evidence (only show when explanation box is maximized)
  const textToParams: Record<string, string[]> = {}
  if (sentenceTexts.length > 0 && aiPanels) {
    const allParams: string[] = Object.keys(aiPanels || {})
    for (const pname of allParams) {
      const ev = aiPanels?.[pname]?.evidence_sentences
      if (Array.isArray(ev)) {
        for (const idx of ev) {
          const t = sentenceTexts[idx]
          if (typeof t === 'string') {
            const key = t.trim()
            if (!textToParams[key]) textToParams[key] = []
            textToParams[key].push(pname)
          }
        }
      }
    }
  }

  const renderOverlayForPage = (pageNum: number) => {
    if (!coords || !Array.isArray(coords) || coords.length === 0) return null
    const vp = pageViewports[pageNum]
    const dims = pages?.[pageNum - 1]
    if (!vp || !dims) return null

    const pageWidth = Number(dims.width || 1)
    const pageHeight = Number(dims.height || 1)


    return (
      <div className="absolute top-0 left-0" style={{ width: vp.width, height: vp.height, zIndex: 10 }}>
        {(() => {
          const pageCoords = Array.isArray(coords)
            ? coords.filter((c: any) => {
                const p = Number(c?.page ?? c?.page_number ?? c?.pageNum ?? 0)
                return p === pageNum
              })
            : []

          const allParams = Object.keys(aiPanels || {})
          const activeParams: string[] = Object.keys(panelOpen || {}).filter((k) => !!panelOpen?.[k])
          const buildCoordKey = (c: any) => {
            const p = Number(c?.page ?? c?.page_number ?? c?.pageNum ?? 0)
            const ulx = Number.parseFloat(c?.ulx ?? c?.x ?? '0')
            const uly = Number.parseFloat(c?.uly ?? c?.y ?? '0')
            const lrx = c?.lrx != null ? Number.parseFloat(c?.lrx) : (c?.width != null ? ulx + Number.parseFloat(c?.width) : ulx)
            const lry = c?.lry != null ? Number.parseFloat(c?.lry) : (c?.height != null ? uly + Number.parseFloat(c?.height) : uly)
            const r = (v: number) => Math.round(v * 100) / 100
            return `p${p}|${r(ulx)}-${r(uly)}-${r(lrx)}-${r(lry)}`
          }
          const openEvidenceCoordKeys = new Set<string>()
          const closedEvidenceCoordKeys = new Set<string>()
          if (allParams.length > 0) {
            for (const pname of allParams) {
              const ev = aiPanels?.[pname]?.evidence_sentences
              if (Array.isArray(ev)) {
                for (const item of ev) {
                  if (item && typeof item === 'object') {
                    const key = buildCoordKey(item)
                    if (activeParams.includes(pname)) openEvidenceCoordKeys.add(key)
                    else closedEvidenceCoordKeys.add(key)
                  }
                }
              }
            }
          }
          // Union of open and closed for filtering (style handled per state)
          const evidenceCoordKeys = new Set<string>([...openEvidenceCoordKeys, ...closedEvidenceCoordKeys])

          const filtered = showBoundingBoxes
            ? pageCoords.filter((c: any) => {
                const t = String(c?.text || '').trim()
                const textMatch = !!t && Array.isArray(textToParams[t]) && textToParams[t].length > 0
                const coordMatch = evidenceCoordKeys.has(buildCoordKey(c))
                return textMatch || coordMatch
              })
            : []


          const elements = filtered.map((c: any, idx: number) => {
            const x = parseFloat(c?.x ?? '0')
            const y = parseFloat(c?.y ?? '0')
            const w = parseFloat(c?.width ?? '0')
            const h = parseFloat(c?.height ?? '0')

            const left = (x / pageWidth) * vp.width
            const top = (y / pageHeight) * vp.height

            // Handle either (ulx,uly,lrx,lry) or (x,y,width,height)
            let width: number
            let height: number
            let mode: 'rightBottom' | 'size'
            if (w > x && h > y) {
              width = Math.max(((w - x) / pageWidth) * vp.width, 0)
              height = Math.max(((h - y) / pageHeight) * vp.height, 0)
              mode = 'rightBottom'
            } else {
              width = Math.max((w / pageWidth) * vp.width, 0)
              height = Math.max((h / pageHeight) * vp.height, 0)
              mode = 'size'
            }

            const t = String(c?.text || '').trim()
            const paramsHere = textToParams[t] || []
            const paramsOpenHere = paramsHere.filter((p) => !!panelOpen?.[p])
            const paramsClosedHere = paramsHere.filter((p) => !panelOpen?.[p])

            // Determine if this coord matches any param via coord evidence
            const key = buildCoordKey(c)
            const coordsParams = (() => {
              const out: string[] = []
              for (const pname of allParams) {
                const ev = aiPanels?.[pname]?.evidence_sentences
                if (Array.isArray(ev)) {
                  for (const item of ev) {
                    if (item && typeof item === 'object' && buildCoordKey(item) === key) {
                      out.push(pname)
                      break
                    }
                  }
                }
              }
              return out
            })()
            const coordsParamsOpen = coordsParams.filter((p) => !!panelOpen?.[p])
            const coordsParamsClosed = coordsParams.filter((p) => !panelOpen?.[p])

            const isOpen = paramsOpenHere.length > 0 || openEvidenceCoordKeys.has(key) || coordsParamsOpen.length > 0
            const isClosed = !isOpen && (paramsClosedHere.length > 0 || closedEvidenceCoordKeys.has(key) || coordsParamsClosed.length > 0)

            const chosenParam =
              (isOpen ? (paramsOpenHere[0] || coordsParamsOpen[0]) : undefined) ??
              (isClosed ? (paramsClosedHere[0] || coordsParamsClosed[0]) : undefined)

            const alpha = isOpen ? 0.2 : 0.05
            const fill = chosenParam ? colorForParam(chosenParam, alpha) : `rgba(255, 229, 100, ${alpha})`
            const borderColor = chosenParam ? solidForParam(chosenParam) : 'rgba(255, 196, 0, 0.95)'
            const border = isOpen ? `2px solid ${borderColor}` : `1px dashed ${borderColor}`
            const title = chosenParam ? `${chosenParam}${t ? `: ${t.slice(0, 160)}` : ''}` : t ? t.slice(0, 160) : 'Sentence'


            return (
              <div
                key={`bb-${pageNum}-${idx}`}
                className="absolute"
                onMouseEnter={() =>
                  setHoverInfo({
                    page: pageNum,
                    left: left + Math.min(width, 180) + 8,
                    top: top,
                    content: title,
                  })
                }
                onMouseMove={(e) => {
                  const parent = e.currentTarget.parentElement as HTMLDivElement | null
                  if (parent) {
                    const rect = parent.getBoundingClientRect()
                    const x = e.clientX - rect.left + 12
                    const y = e.clientY - rect.top + 12
                    setHoverInfo({ page: pageNum, left: x, top: y, content: title })
                  }
                }}
                onMouseLeave={() => {
                  setHoverInfo((info) => (info && info.page === pageNum ? null : info))
                }}
                style={{
                  left,
                  top,
                  width,
                  height,
                  background: fill,
                  border: border,
                  borderRadius: 2,
                  boxSizing: 'border-box',
                  // Make sure highlights are visible above the canvas drawing
                  mixBlendMode: 'multiply',
                  cursor: 'help',
                  pointerEvents: 'auto',
                }}
              />
            )
          })

          return (
            <>
              {elements}
              {hoverInfo && hoverInfo.page === pageNum && (
                <div
                  className="absolute z-20 max-w-[260px] rounded bg-black/75 px-2 py-1 text-xs text-white shadow-lg"
                  style={{ left: hoverInfo.left, top: hoverInfo.top, pointerEvents: 'none' }}
                >
                  {hoverInfo.content}
                </div>
              )}
            </>
          )
        })()}
      </div>
    )
  }

  return (
    <div className="rounded-md border border-gray-200 bg-white p-4">
      <div className="mb-3 flex items-center justify-between">
        <div>
          <div className="text-xs text-gray-600">Citation #{citationId}</div>
          <div className="text-lg font-semibold text-gray-900">{fileName || dict.pdf.fullText}</div>
        </div>
        <div className="flex items-center gap-3">
          <label className="flex items-center text-sm">
            <input
              type="checkbox"
              checked={showBoundingBoxes}
              onChange={(e) => setShowBoundingBoxes(e.target.checked)}
              className="mr-2"
            />
            {dict.pdf.showEvidenceHighlights}
          </label>
          <div className="ml-3 text-xs text-gray-500">{Math.round(scale * 100)}%</div>
        </div>
      </div>

      <div className="space-y-3">
        <div className="flex items-center gap-3">
          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={() => {
                setFitToWidth(false)
                setScale((s) => Math.max(0.5, s - 0.2))
              }}
              className="rounded-md border px-2 py-1 text-sm"
            >
              -
            </button>
            <button
              onClick={() => {
                setFitToWidth(false)
                setScale((s) => Math.min(3, s + 0.2))
              }}
              className="rounded-md border px-2 py-1 text-sm"
            >
              +
            </button>
            <button
              onClick={() => {
                setFitToWidth(false)
                setScale(1.0)
              }}
              className="rounded-md border px-2 py-1 text-sm"
            >
              100%
            </button>
            <button onClick={() => setFitToWidth((v) => !v)} className="rounded-md border px-2 py-1 text-sm">
              {dict.pdf.fit}
            </button>
          </div>
        </div>

        <div className="relative">
          <div
            ref={containerRef}
            className="h-[680px] overflow-auto border rounded p-4 bg-gray-50 flex justify-center items-start"
          >
            {loading ? (
              <div className="text-sm text-gray-600">{dict.pdf.loadingPDF}</div>
            ) : error ? (
              <div className="text-sm text-red-600">{error}</div>
            ) : (
              <div className="w-full flex flex-col items-center gap-6">
                {Array.from({ length: totalPages }, (_, i) => i + 1).map((pageNum) => {
                  const vp = pageViewports[pageNum]
                  return (
                    <div key={pageNum} className="w-full flex flex-col items-center">
                      <div className="mb-2 text-sm text-gray-700 font-medium">{dict.screening.page} {pageNum}</div>
                      <div
                        ref={(el) => {
                          wrapperRefs.current[pageNum] = el
                        }}
                        className="relative"
                        style={
                          vp
                            ? { width: vp.width, height: vp.height }
                            : { width: 'auto', height: 'auto' }
                        }
                      >
                        <canvas
                          ref={(el) => {
                            pageRefs.current[pageNum] = el
                          }}
                          style={{
                            maxWidth: '100%',
                            height: 'auto',
                            background: 'white',
                            border: '1px solid #e5e7eb',
                            position: 'relative',
                            zIndex: 1,
                          }}
                        />
                        {renderOverlayForPage(pageNum)}
                      </div>
                    </div>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="flex items-center justify-between">
          <div className="text-xs text-gray-500">{fileName}</div>
          <div className="text-xs text-gray-400">{dict.pdf.keyboardHint}</div>
        </div>
      </div>
    </div>
  )
});

export default PDFBoundingBoxViewer
