import i18n from "../i18n";
import { useEffect, useRef, useState, type ReactNode } from "react";
import * as pdfjs from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";

pdfjs.GlobalWorkerOptions.workerSrc = workerUrl;

export interface PageSize {
  number: number;
  width: number;
  height: number;
}

const MAX_PAGE_WIDTH = 880;

/** Renders every page of a PDF as a canvas, scaled to the available width, and
 *  lets the caller lay an overlay (the placed elements) on each page. The PDF is
 *  fetched with the session cookie and handed to PDF.js as bytes. Scripts inside
 *  the document are never run (PDF.js does not execute them here, and the upload
 *  check also refuses active content). */
export default function PdfPages({
  url,
  pages,
  renderOverlay,
}: {
  url: string;
  pages: PageSize[];
  renderOverlay: (page: PageSize, element: HTMLDivElement | null) => ReactNode;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(MAX_PAGE_WIDTH);
  const [doc, setDoc] = useState<pdfjs.PDFDocumentProxy | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const el = containerRef.current;
    if (!el || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => {
      setWidth(Math.max(280, Math.min(el.clientWidth, MAX_PAGE_WIDTH)));
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    let task: pdfjs.PDFDocumentLoadingTask | null = null;
    (async () => {
      try {
        const response = await fetch(url, { credentials: "same-origin" });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const data = new Uint8Array(await response.arrayBuffer());
        task = pdfjs.getDocument({ data });
        const loaded = await task.promise;
        if (!cancelled) setDoc(loaded);
      } catch {
        if (!cancelled) setError(i18n.t("pdf.cannotDisplay"));
      }
    })();
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [url]);

  return (
    <div ref={containerRef} className="prep-pages">
      {error && <p className="error-text">{error}</p>}
      {!doc && !error && <p className="muted">{i18n.t("pdf.loading")}</p>}
      {doc &&
        pages.map((page) => (
          <Page key={page.number} doc={doc} page={page} width={width} renderOverlay={renderOverlay} />
        ))}
    </div>
  );
}

function Page({
  doc,
  page,
  width,
  renderOverlay,
}: {
  doc: pdfjs.PDFDocumentProxy;
  page: PageSize;
  width: number;
  renderOverlay: (page: PageSize, element: HTMLDivElement | null) => ReactNode;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const frameRef = useRef<HTMLDivElement>(null);
  const [frame, setFrame] = useState<HTMLDivElement | null>(null);
  const height = (width * page.height) / page.width;

  useEffect(() => setFrame(frameRef.current), []);

  useEffect(() => {
    let task: pdfjs.RenderTask | null = null;
    let cancelled = false;
    (async () => {
      const pdfPage = await doc.getPage(page.number);
      const canvas = canvasRef.current;
      if (cancelled || !canvas) return;
      const base = pdfPage.getViewport({ scale: 1 });
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      const viewport = pdfPage.getViewport({ scale: (width / base.width) * ratio });
      canvas.width = Math.floor(viewport.width);
      canvas.height = Math.floor(viewport.height);
      task = pdfPage.render({ canvas, viewport });
      try {
        await task.promise;
      } catch {
        // A render cancelled by a resize or unmount is expected.
      }
    })();
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [doc, page.number, width]);

  return (
    <div className="prep-page-wrap">
      <div className="prep-page-number">{i18n.t("pdf.page", { n: page.number })}</div>
      <div
        ref={frameRef}
        className="prep-page"
        style={{ width, height }}
        data-page={page.number}
        data-testid={`page-${page.number}`}
      >
        <canvas ref={canvasRef} style={{ width: "100%", height: "100%" }} />
        {renderOverlay(page, frame)}
      </div>
    </div>
  );
}
