<script lang="ts">
  import * as d3 from "d3";
  import { onMount } from "svelte";
  import type { GraphEdge, GraphNode, GraphPayload } from "./graph";
  import { communityColor, hexToRgb } from "./palette";

  type SimNode = GraphNode & d3.SimulationNodeDatum & { r: number; color: string; rank: number };
  type SimLink = { source: SimNode; target: SimNode; weight: number; shared: number };
  type Insets = { top: number; right: number; bottom: number; left: number };
  type ClusterLabel = { id: number; label: string; size: number };
  export type ClusterHover = { id: number; x: number; y: number } | null;

  let {
    graph,
    minWeight = 0.05,
    highlight = null,
    focusId = null,
    hoverId = $bindable(null),
    insets = { top: 0, right: 0, bottom: 0, left: 0 },
    clusters = [],
    clusterHover = $bindable(null),
    onselect,
    onclusterselect,
  }: {
    graph: GraphPayload;
    minWeight?: number;
    highlight?: Set<number> | null;
    focusId?: number | null;
    hoverId?: number | null;
    insets?: Insets;
    clusters?: ClusterLabel[];
    clusterHover?: ClusterHover;
    onselect: (id: number | null) => void;
    onclusterselect?: (id: number) => void;
  } = $props();

  const EDGE_SLATE = "#5A6382";
  const LABEL_INK = "#ECE6D8";
  const reduceMotion =
    typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches;

  let canvas: HTMLCanvasElement;
  let ctx: CanvasRenderingContext2D;
  let width = 0;
  let height = 0;
  let dpr = 1;
  let transform = d3.zoomIdentity;
  let zoom: d3.ZoomBehavior<HTMLCanvasElement, unknown>;
  let userMoved = false;
  let frame = 0;

  let nodes: SimNode[] = [];
  let links: SimLink[] = [];
  let byId = new Map<number, SimNode>();
  let tree: d3.Quadtree<SimNode> | null = null;
  let simulation: d3.Simulation<SimNode, SimLink> | null = null;
  const glowSprites = new Map<string, HTMLCanvasElement>();
  // Screen-space boxes of the cluster names drawn last frame, for hit-testing.
  let overlayHits: { id: number; x: number; y: number; w: number; h: number }[] = [];

  /** Cluster names own the overview; they fade out as you zoom into films. */
  function overlayStrength(): number {
    if (highlight) return 0;
    return Math.max(0, Math.min(1, (1.9 - transform.k / baseScale) / 0.9));
  }
  let baseScale = 1;

  // ---------------------------------------------------------------- layout

  function build(payload: GraphPayload) {
    simulation?.stop();
    const random = d3.randomLcg(42);

    const ranked = [...payload.nodes].sort((a, b) => (b.degree ?? 0) - (a.degree ?? 0));
    const rankOf = new Map(ranked.map((n, i) => [n.id, i]));

    // Pack one circle per community so clusters get their own territory;
    // nodes are then pulled weakly toward their community's anchor.
    const sizes = d3.rollup(payload.nodes, (v) => v.length, (n) => n.community ?? -1);
    const circles = [...sizes.entries()]
      .sort((a, b) => b[1] - a[1])
      .map(([community, size]) => ({ community, r: Math.sqrt(size) * 16, x: 0, y: 0 }));
    d3.packSiblings(circles);
    const anchors = new Map(circles.map((c) => [c.community, c]));

    nodes = payload.nodes.map((n) => {
      const anchor = anchors.get(n.community ?? -1)!;
      const angle = random() * Math.PI * 2;
      const dist = Math.sqrt(random()) * anchor.r;
      return {
        ...n,
        r: 2.2 + Math.sqrt(n.degree ?? 0) * 1.25,
        color: communityColor(n.community),
        rank: rankOf.get(n.id)!,
        x: anchor.x + Math.cos(angle) * dist,
        y: anchor.y + Math.sin(angle) * dist,
      };
    });
    byId = new Map(nodes.map((n) => [n.id, n]));
    links = payload.edges
      .filter((e: GraphEdge) => byId.has(e.source) && byId.has(e.target))
      .map((e) => ({
        source: byId.get(e.source)!,
        target: byId.get(e.target)!,
        weight: e.weight,
        shared: e.shared,
      }));

    simulation = d3
      .forceSimulation<SimNode, SimLink>(nodes)
      .randomSource(random)
      .force(
        "link",
        d3
          .forceLink<SimNode, SimLink>(links)
          .distance((l) => 18 + (1 - l.weight) * 40)
          .strength((l) =>
            l.source.community === l.target.community ? 0.15 + l.weight : 0.02 + l.weight * 0.1,
          ),
      )
      .force("charge", d3.forceManyBody<SimNode>().strength(-22).distanceMax(220))
      .force("collide", d3.forceCollide<SimNode>((n) => n.r + 1.5))
      .force("x", d3.forceX<SimNode>((n) => anchors.get(n.community ?? -1)!.x).strength(0.06))
      .force("y", d3.forceY<SimNode>((n) => anchors.get(n.community ?? -1)!.y).strength(0.06))
      .alphaDecay(0.025)
      .stop();

    if (reduceMotion) {
      simulation.tick(320);
      settle();
    } else {
      // Pre-settle a little so the opening frame already reads as clusters,
      // then let the remainder play out as the page's one motion moment.
      simulation.tick(40);
      simulation.on("tick", () => {
        tree = null;
        schedule();
      });
      simulation.on("end", settle);
      simulation.restart();
    }

    if (!userMoved) fitTo(nodes, false);
    schedule();
  }

  function settle() {
    tree = null;
    if (!userMoved && !highlight) fitTo(nodes, !reduceMotion);
    schedule();
  }

  function quadtree() {
    tree ??= d3
      .quadtree<SimNode>()
      .x((n) => n.x!)
      .y((n) => n.y!)
      .addAll(nodes);
    return tree;
  }

  // ---------------------------------------------------------------- camera

  function fitTo(subset: SimNode[], animate: boolean, maxScale = 3.5) {
    if (!subset.length || !width) return;
    const [x0, x1] = d3.extent(subset, (n) => n.x!) as [number, number];
    const [y0, y1] = d3.extent(subset, (n) => n.y!) as [number, number];
    const pad = 40;
    const availW = Math.max(80, width - insets.left - insets.right - pad * 2);
    const availH = Math.max(80, height - insets.top - insets.bottom - pad * 2);
    const k = Math.min(maxScale, availW / Math.max(1, x1 - x0), availH / Math.max(1, y1 - y0));
    const cx = insets.left + pad + availW / 2;
    const cy = insets.top + pad + availH / 2;
    const target = d3.zoomIdentity
      .translate(cx, cy)
      .scale(k)
      .translate(-(x0 + x1) / 2, -(y0 + y1) / 2);

    if (subset === nodes) baseScale = k;
    const selection = d3.select(canvas);
    if (animate && !reduceMotion) {
      selection.transition().duration(750).ease(d3.easeCubicInOut).call(zoom.transform, target);
    } else {
      selection.call(zoom.transform, target);
    }
  }

  // ---------------------------------------------------------------- drawing

  function glow(color: string): HTMLCanvasElement {
    let sprite = glowSprites.get(color);
    if (sprite) return sprite;
    sprite = document.createElement("canvas");
    sprite.width = sprite.height = 64;
    const g = sprite.getContext("2d")!;
    const [r, gg, b] = hexToRgb(color);
    const gradient = g.createRadialGradient(32, 32, 0, 32, 32, 32);
    gradient.addColorStop(0, `rgba(${r},${gg},${b},0.55)`);
    gradient.addColorStop(0.35, `rgba(${r},${gg},${b},0.18)`);
    gradient.addColorStop(1, `rgba(${r},${gg},${b},0)`);
    g.fillStyle = gradient;
    g.fillRect(0, 0, 64, 64);
    glowSprites.set(color, sprite);
    return sprite;
  }

  function schedule() {
    if (!frame) frame = requestAnimationFrame(draw);
  }

  function curve(path: Path2D, a: SimNode, b: SimNode) {
    // A gentle, consistent bow: control point offset perpendicular to the chord.
    const mx = (a.x! + b.x!) / 2;
    const my = (a.y! + b.y!) / 2;
    const dx = b.x! - a.x!;
    const dy = b.y! - a.y!;
    path.moveTo(a.x!, a.y!);
    path.quadraticCurveTo(mx - dy * 0.12, my + dx * 0.12, b.x!, b.y!);
  }

  function draw() {
    frame = 0;
    if (!ctx) return;
    const k = transform.k;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.save();
    ctx.translate(transform.x, transform.y);
    ctx.scale(k, k);

    const lit = highlight;
    const isLit = (n: SimNode) => !lit || lit.has(n.id);

    // Edges, batched into one path per (color, alpha bucket) so a few
    // thousand links cost a handful of stroke calls.
    const batches = new Map<string, Path2D>();
    for (const l of links) {
      if (l.weight < minWeight) continue;
      const on = isLit(l.source) && isLit(l.target);
      const same = l.source.community === l.target.community;
      const color = on && same ? l.source.color : EDGE_SLATE;
      const alpha = !on ? 0.03 : lit ? 0.3 + l.weight * 0.7 : 0.06 + l.weight * 0.5;
      const key = `${color}|${Math.min(9, Math.round(alpha * 10))}|${on && lit ? 1 : 0}`;
      let path = batches.get(key);
      if (!path) batches.set(key, (path = new Path2D()));
      curve(path, l.source, l.target);
    }
    for (const [key, path] of batches) {
      const [color, bucket, strong] = key.split("|");
      ctx.strokeStyle = color;
      ctx.globalAlpha = Math.max(0.03, Number(bucket) / 10);
      ctx.lineWidth = (strong === "1" ? 1.4 : 0.8) / Math.sqrt(k);
      ctx.stroke(path);
    }

    // Territories: a faint wash of each cluster's hue at overview zoom, so the
    // named regions read as places before you read any dots.
    const strength = overlayStrength();
    if (strength > 0) {
      for (const t of territories()) {
        const g = t.radius * 2.2;
        ctx.globalAlpha = 0.22 * strength;
        ctx.drawImage(glow(t.color), t.x - g, t.y - g, g * 2, g * 2);
      }
    }

    // Nodes: a soft glow sprite under a solid core. Dimmed nodes skip the glow.
    for (const n of nodes) {
      const on = isLit(n);
      if (on) {
        const g = n.r * 5;
        ctx.globalAlpha = n.id === focusId ? 1 : 0.85;
        ctx.drawImage(glow(n.color), n.x! - g, n.y! - g, g * 2, g * 2);
      }
      ctx.globalAlpha = on ? 1 : 0.16;
      ctx.fillStyle = n.color;
      ctx.beginPath();
      ctx.arc(n.x!, n.y!, n.r, 0, Math.PI * 2);
      ctx.fill();
    }

    for (const id of [focusId, hoverId]) {
      const n = id != null ? byId.get(id) : undefined;
      if (!n) continue;
      ctx.globalAlpha = 1;
      ctx.strokeStyle = LABEL_INK;
      ctx.lineWidth = 1.5 / k;
      ctx.beginPath();
      ctx.arc(n.x!, n.y!, n.r + 3.5 / k, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.restore();

    drawLabels();
  }

  function territories() {
    const acc = new Map<number, { sx: number; sy: number; n: number; color: string; pts: SimNode[] }>();
    for (const n of nodes) {
      if (n.community == null) continue;
      let a = acc.get(n.community);
      if (!a) acc.set(n.community, (a = { sx: 0, sy: 0, n: 0, color: n.color, pts: [] }));
      a.sx += n.x!;
      a.sy += n.y!;
      a.n += 1;
      a.pts.push(n);
    }
    return [...acc.entries()].map(([id, a]) => {
      const x = a.sx / a.n;
      const y = a.sy / a.n;
      const spread = Math.sqrt(a.pts.reduce((s, p) => s + (p.x! - x) ** 2 + (p.y! - y) ** 2, 0) / a.n);
      return { id, x, y, radius: spread, color: a.color, size: a.n };
    });
  }

  function drawOverlay(placed: [number, number, number, number][]) {
    overlayHits = [];
    const strength = overlayStrength();
    if (strength <= 0.02 || !clusters.length) return;
    const names = new Map(clusters.map((c) => [c.id, c]));
    const regions = territories().sort((a, b) => b.size - a.size);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    for (const r of regions) {
      const c = names.get(r.id);
      if (!c) continue;
      const [sx, sy] = transform.apply([r.x, r.y]);
      const size = Math.round(Math.max(12, Math.min(20, 9 + Math.sqrt(r.size) * 0.9)));
      ctx.font = `italic ${size}px "Instrument Serif", Georgia, serif`;
      const w = ctx.measureText(c.label).width;
      const box: [number, number, number, number] = [sx - w / 2 - 6, sy - size / 2 - 4, w + 12, size + 8];
      if (placed.some(([px, py, pw, ph]) => box[0] < px + pw && box[0] + box[2] > px && box[1] < py + ph && box[1] + box[3] > py)) continue;
      placed.push(box);
      const hovered = clusterHover?.id === r.id;
      // Translucent by design: the names sit over the map, not on top of it.
      ctx.globalAlpha = strength * (hovered ? 1 : 0.5);
      ctx.lineWidth = 3;
      ctx.lineJoin = "round";
      ctx.strokeStyle = "rgba(20, 26, 46, 0.55)";
      ctx.strokeText(c.label, sx, sy);
      ctx.globalAlpha = strength * (hovered ? 1 : 0.82);
      ctx.fillStyle = hovered ? LABEL_INK : r.color;
      ctx.fillText(c.label, sx, sy);
      if (hovered) {
        ctx.fillRect(sx - w / 2, sy + size / 2 + 1, w, 1);
      }
      overlayHits.push({ id: r.id, x: box[0], y: box[1], w: box[2], h: box[3] });
    }
    ctx.globalAlpha = 1;
    ctx.textAlign = "start";
  }

  function drawLabels() {
    const k = transform.k;
    const lit = highlight;
    const placed: [number, number, number, number][] = [];
    const overlaps = (x: number, y: number, w: number, h: number) =>
      placed.some(([px, py, pw, ph]) => x < px + pw && x + w > px && y < py + ph && y + h > py);

    // Hub labels only: the label budget grows with zoom so detail arrives as
    // you move in, rather than all 1,800 titles fighting at once.
    const strength = overlayStrength();
    drawOverlay(placed);
    const budget = lit ? 80 : Math.round((10 + 10 * k * k) * (1 - strength));
    const pool = (lit ? nodes.filter((n) => lit.has(n.id)) : nodes)
      .slice()
      .sort((a, b) => a.rank - b.rank);
    const ordered: SimNode[] = [];
    for (const id of [focusId, hoverId]) {
      const n = id != null ? byId.get(id) : undefined;
      if (n) ordered.push(n);
    }
    ordered.push(...pool.slice(0, budget));

    ctx.textBaseline = "middle";
    const seen = new Set<number>();
    for (const n of ordered) {
      if (seen.has(n.id)) continue;
      seen.add(n.id);
      const [sx, sy] = transform.apply([n.x!, n.y!]);
      if (sx < -50 || sy < -20 || sx > width + 50 || sy > height + 20) continue;

      const primary = n.id === focusId || n.id === hoverId;
      ctx.font = primary
        ? 'italic 20px "Instrument Serif", Georgia, serif'
        : '500 12px "Archivo", system-ui, sans-serif';
      if (!primary) ctx.fontStretch = "condensed";
      const text = primary && n.year ? `${n.label} (${n.year})` : n.label;
      const w = ctx.measureText(text).width;
      const h = primary ? 22 : 14;
      const x = sx + n.r * k + 6;
      const y = sy - h / 2;
      if (!primary && overlaps(x - 2, y, w + 4, h)) continue;
      placed.push([x - 2, y, w + 4, h]);

      ctx.globalAlpha = 1;
      ctx.lineWidth = 3;
      ctx.strokeStyle = "rgba(20, 26, 46, 0.85)";
      ctx.lineJoin = "round";
      ctx.strokeText(text, x, sy);
      ctx.fillStyle = primary ? LABEL_INK : "rgba(236, 230, 216, 0.78)";
      ctx.fillText(text, x, sy);
      ctx.fontStretch = "normal";
    }
  }

  // ---------------------------------------------------------------- input

  function pick(event: MouseEvent): SimNode | undefined {
    const rect = canvas.getBoundingClientRect();
    const [x, y] = transform.invert([event.clientX - rect.left, event.clientY - rect.top]);
    const n = quadtree().find(x, y, 14 / transform.k + 6);
    if (!n) return undefined;
    if (highlight && !highlight.has(n.id) && n.id !== focusId) {
      // Dimmed nodes are still clickable, but only on a direct hit.
      if (Math.hypot(n.x! - x, n.y! - y) > n.r + 2 / transform.k) return undefined;
    }
    return n;
  }

  function resize() {
    const rect = canvas.parentElement!.getBoundingClientRect();
    width = rect.width;
    height = rect.height;
    dpr = window.devicePixelRatio || 1;
    canvas.width = Math.round(width * dpr);
    canvas.height = Math.round(height * dpr);
    canvas.style.width = `${width}px`;
    canvas.style.height = `${height}px`;
    schedule();
  }

  onMount(() => {
    ctx = canvas.getContext("2d")!;
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas.parentElement!);

    zoom = d3
      .zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.08, 10])
      .on("zoom", (event) => {
        transform = event.transform;
        if (event.sourceEvent) userMoved = true;
        schedule();
      });
    d3.select(canvas).call(zoom).on("dblclick.zoom", null);

    const overlayAt = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const x = event.clientX - rect.left;
      const y = event.clientY - rect.top;
      return overlayHits.find((h) => x >= h.x && x <= h.x + h.w && y >= h.y && y <= h.y + h.h);
    };
    canvas.addEventListener("click", (event) => {
      const hit = overlayAt(event);
      if (hit && onclusterselect) return onclusterselect(hit.id);
      onselect(pick(event)?.id ?? null);
    });
    canvas.addEventListener("mousemove", (event) => {
      const hit = overlayAt(event);
      if (hit) {
        if (clusterHover?.id !== hit.id) {
          const rect = canvas.getBoundingClientRect();
          clusterHover = { id: hit.id, x: hit.x + hit.w / 2 + rect.left, y: hit.y + hit.h + rect.top };
          schedule();
        }
        hoverId = null;
        canvas.style.cursor = "pointer";
        return;
      }
      if (clusterHover) {
        clusterHover = null;
        schedule();
      }
      const id = pick(event)?.id ?? null;
      if (id !== hoverId) {
        hoverId = id;
        canvas.style.cursor = id != null ? "pointer" : "grab";
        schedule();
      }
    });
    canvas.addEventListener("mouseleave", () => {
      hoverId = null;
      clusterHover = null;
      schedule();
    });

    if (import.meta.env.DEV) {
      (window as unknown as Record<string, unknown>).__map = () => ({
        k: transform.k, x: transform.x, y: transform.y, nodes: nodes.length,
        width, height, lit: highlight?.size ?? 0,
        sample: nodes.slice(0, 2).map((n) => [n.x, n.y]),
      });
    }

    // Fonts load after first paint; redraw labels once they're in.
    document.fonts?.ready.then(schedule);

    return () => {
      observer.disconnect();
      simulation?.stop();
      cancelAnimationFrame(frame);
    };
  });

  // Rebuild only when the payload itself changes.
  let builtFor: GraphPayload | null = null;
  $effect(() => {
    if (ctx && graph !== builtFor) {
      builtFor = graph;
      build(graph);
    }
  });

  // Move the camera to whatever is lit: a film's neighborhood or a cluster.
  $effect(() => {
    const lit = highlight;
    if (!ctx || !lit) return;
    const subset = nodes.filter((n) => lit.has(n.id));
    if (subset.length) {
      userMoved = true;
      fitTo(subset, true, subset.length === 1 ? 3 : 3.5);
    }
  });

  $effect(() => {
    // Track the visual inputs so any change repaints.
    void [minWeight, highlight, focusId, hoverId, clusters, clusterHover];
    schedule();
  });

  export function resetView() {
    userMoved = false;
    fitTo(nodes, true);
  }
</script>

<canvas
  bind:this={canvas}
  aria-label="Network of watched films. Each dot is a film; lines join films the same viewers watch. Use the search box to pick a film."
></canvas>

<style>
  canvas {
    display: block;
    cursor: grab;
    touch-action: none;
  }
  canvas:active {
    cursor: grabbing;
  }
</style>
