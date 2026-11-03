<script lang="ts">
  import { onMount } from "svelte";
  import GraphCanvas, { type ClusterHover } from "./lib/GraphCanvas.svelte";
  import ClusterCard from "./lib/ClusterCard.svelte";
  import ClusterPanel from "./lib/ClusterPanel.svelte";
  import RecList from "./lib/RecList.svelte";
  import type { ClusterProfile, GraphNode, GraphPayload, Recommendation } from "./lib/graph";
  import { communityColor } from "./lib/palette";
  import { genreList } from "./lib/format";

  type Neighbor = { node: GraphNode; weight: number; shared: number };
  type LoadError = { title: string; hint: string };

  let graph = $state<GraphPayload | null>(null);
  let error = $state<LoadError | null>(null);
  let selectedId = $state<number | null>(null);
  let clusterId = $state<number | null>(null);
  let hoverId = $state<number | null>(null);
  let minWeight = $state(0.05);
  let query = $state("");
  let searchOpen = $state(false);
  let searchInput = $state<HTMLInputElement>();
  let canvasRef: ReturnType<typeof GraphCanvas> | undefined = $state();
  let wide = $state(true);
  let clusterHover = $state<ClusterHover>(null);
  let railTab = $state<"clusters" | "picks">("clusters");

  onMount(() => {
    const mq = matchMedia("(min-width: 760px)");
    wide = mq.matches;
    mq.addEventListener("change", (e) => (wide = e.matches));
    load();
    addEventListener("hashchange", readHash);
  });

  // Deep links: #film=<trakt id> or #cluster=<index>.
  function readHash() {
    const params = new URLSearchParams(location.hash.slice(1));
    const film = Number(params.get("film"));
    const cluster = Number(params.get("cluster"));
    selectedId = params.has("film") && Number.isFinite(film) ? film : null;
    clusterId = !params.has("film") && params.has("cluster") && Number.isFinite(cluster) ? cluster : null;
  }

  $effect(() => {
    if (!graph) return; // don't clobber an incoming link before it's been read
    const hash = selectedId != null ? `#film=${selectedId}` : clusterId != null ? `#cluster=${clusterId}` : "";
    if (hash !== location.hash) history.replaceState(null, "", hash || location.pathname);
  });

  async function load() {
    try {
      const res = await fetch("/api/graph");
      if (res.status === 409) {
        error = {
          title: "No films ingested yet",
          hint: "Run uv run trakt-ify ingest, then reload this page.",
        };
        return;
      }
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      graph = await res.json();
      readHash();
    } catch {
      error = {
        title: "The graph API isn't responding",
        hint: "Start it with uv run trakt-ify serve, then reload this page.",
      };
    }
  }

  const nodesById = $derived(new Map((graph?.nodes ?? []).map((n) => [n.id, n])));

  const adjacency = $derived.by(() => {
    const adj = new Map<number, Neighbor[]>();
    if (!graph) return adj;
    for (const e of graph.edges) {
      const s = nodesById.get(e.source);
      const t = nodesById.get(e.target);
      if (!s || !t) continue;
      (adj.get(s.id) ?? adj.set(s.id, []).get(s.id)!).push({ node: t, weight: e.weight, shared: e.shared });
      (adj.get(t.id) ?? adj.set(t.id, []).get(t.id)!).push({ node: s, weight: e.weight, shared: e.shared });
    }
    for (const list of adj.values()) list.sort((a, b) => b.weight - a.weight);
    return adj;
  });

  const selected = $derived(selectedId != null ? nodesById.get(selectedId) ?? null : null);
  const neighbors = $derived(
    selectedId != null ? (adjacency.get(selectedId) ?? []).filter((n) => n.weight >= minWeight) : [],
  );

  const profiles = $derived(new Map((graph?.clusters ?? []).map((c) => [c.id, c])));

  const members = $derived.by(() => {
    const groups = new Map<number, number[]>();
    for (const n of graph?.nodes ?? []) {
      if (n.community == null) continue;
      (groups.get(n.community) ?? groups.set(n.community, []).get(n.community)!).push(n.id);
    }
    return groups;
  });

  const clusterList = $derived(
    (graph?.clusters ?? []).map((c) => ({ ...c, color: communityColor(c.id) })),
  );
  const overlayLabels = $derived(clusterList.map((c) => ({ id: c.id, label: c.label, size: c.size })));
  const openCluster = $derived(clusterId != null ? (profiles.get(clusterId) ?? null) : null);
  const hoveredCluster = $derived(clusterHover ? (profiles.get(clusterHover.id) ?? null) : null);

  const bestBets = $derived(
    (graph?.clusters ?? [])
      .flatMap((c) => c.recommendations ?? [])
      .sort((a, b) => b.score - a.score)
      .slice(0, 20),
  );
  const homeOf = new Map<number, ClusterProfile>();
  $effect(() => {
    homeOf.clear();
    for (const c of graph?.clusters ?? []) for (const r of c.recommendations ?? []) homeOf.set(r.id, c);
  });
  function homeLabel(r: Recommendation) {
    const c = homeOf.get(r.id);
    return c ? { label: c.label, color: communityColor(c.id) } : null;
  }

  function hoverRow(event: Event, id: number) {
    const rect = (event.currentTarget as HTMLElement).getBoundingClientRect();
    clusterHover = { id, x: rect.right + 170, y: rect.top - 8 };
  }

  const highlight = $derived.by(() => {
    if (selectedId != null) return new Set([selectedId, ...neighbors.map((n) => n.node.id)]);
    if (clusterId != null) {
      const ids = members.get(clusterId);
      return ids ? new Set(ids) : null;
    }
    return null;
  });

  const results = $derived.by(() => {
    const q = query.trim().toLowerCase();
    if (!graph || q.length < 2) return [];
    return graph.nodes
      .filter((n) => n.label.toLowerCase().includes(q))
      .sort((a, b) => {
        const ap = a.label.toLowerCase().startsWith(q) ? 0 : 1;
        const bp = b.label.toLowerCase().startsWith(q) ? 0 : 1;
        return ap - bp || (b.degree ?? 0) - (a.degree ?? 0);
      })
      .slice(0, 8);
  });

  const insets = $derived(
    wide
      ? { top: 0, left: 360, right: selected || openCluster ? 410 : 0, bottom: 0 }
      : { top: 120, left: 0, right: 0, bottom: selected || openCluster ? 340 : 0 },
  );

  function select(id: number | null) {
    selectedId = id;
    if (id != null) clusterId = null;
    searchOpen = false;
  }

  function showCluster(id: number) {
    selectedId = null;
    clusterHover = null;
    clusterId = clusterId === id && !selectedId ? null : id;
  }

  function clearFocus() {
    selectedId = null;
    clusterId = null;
  }

  function onKey(event: KeyboardEvent) {
    const typing = event.target instanceof HTMLInputElement;
    if (event.key === "Escape") {
      if (typing && query) {
        query = "";
        return;
      }
      clearFocus();
      searchInput?.blur();
    } else if (event.key === "/" && !typing) {
      event.preventDefault();
      searchInput?.focus();
    }
  }

  const fmt = new Intl.NumberFormat("en-US");
  const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" });

  function watchedLine(n: GraphNode): string {
    const plays = n.plays ?? 0;
    const times = plays <= 1 ? "Watched once" : `Watched ${plays} times`;
    return n.lastWatchedAt ? `${times}, last on ${dateFmt.format(new Date(n.lastWatchedAt))}` : times;
  }
</script>

<svelte:window onkeydown={onKey} />

<main>
  <div class="stage">
    {#if graph}
      <GraphCanvas
        bind:this={canvasRef}
        bind:hoverId
        {graph}
        {minWeight}
        {highlight}
        focusId={selectedId}
        {insets}
        clusters={overlayLabels}
        bind:clusterHover
        onselect={select}
        onclusterselect={showCluster}
      />
    {/if}
  </div>

  {#if error}
    <div class="notice" role="alert">
      <h1>{error.title}</h1>
      <p>{error.hint}</p>
    </div>
  {:else if !graph}
    <p class="loading">Drawing your film map…</p>
  {:else}
    <aside class="rail">
      <header>
        <h1>{graph.meta.username}’s film map</h1>
        <p class="lede">
          {fmt.format(graph.meta.nodeCount)} of {fmt.format(graph.meta.movieCount)} watched films, in
          {graph.meta.communityCount} clusters. Films sit together when the same people watch them. Hover a
          cluster’s name to see what it is, or open it for what to watch next.
        </p>
      </header>

      <div class="search">
        <label class="visually-hidden" for="search">Find a film</label>
        <input
          id="search"
          bind:this={searchInput}
          bind:value={query}
          onfocus={() => (searchOpen = true)}
          onblur={() => setTimeout(() => (searchOpen = false), 150)}
          placeholder="Find a film  ( / )"
          autocomplete="off"
          spellcheck="false"
        />
        {#if searchOpen && results.length}
          <ul class="results">
            {#each results as r (r.id)}
              <li>
                <button onclick={() => select(r.id)}>
                  <span class="dot" style:background={communityColor(r.community)}></span>
                  <span class="film">{r.label}</span>
                  {#if r.year}<span class="year">{r.year}</span>{/if}
                </button>
              </li>
            {/each}
          </ul>
        {:else if searchOpen && query.trim().length >= 2}
          <p class="empty">No film in the map matches “{query.trim()}”.</p>
        {/if}
      </div>

      <div class="control">
        <label for="weight">
          Hide links with overlap under <output>{Math.round(minWeight * 100)}%</output>
        </label>
        <input id="weight" type="range" min="0.05" max="0.4" step="0.01" bind:value={minWeight} />
      </div>

      <div class="tabs" role="tablist">
        <button role="tab" aria-selected={railTab === "clusters"} onclick={() => (railTab = "clusters")}>Clusters</button>
        <button role="tab" aria-selected={railTab === "picks"} onclick={() => (railTab = "picks")}>Best bets</button>
      </div>

      {#if railTab === "clusters"}
        <section class="clusters" aria-label="Clusters">
          <ul>
            {#each clusterList as c (c.id)}
              <li>
                <button
                  class:active={clusterId === c.id}
                  aria-pressed={clusterId === c.id}
                  onclick={() => showCluster(c.id)}
                  onmouseenter={(e) => wide && hoverRow(e, c.id)}
                  onmouseleave={() => (clusterHover = null)}
                  onfocus={(e) => wide && hoverRow(e, c.id)}
                  onblur={() => (clusterHover = null)}
                  style:--hue={c.color}
                >
                  <span class="dot"></span>
                  <span class="name">{c.label}</span>
                  <span class="count">{c.size}</span>
                </button>
              </li>
            {/each}
          </ul>
        </section>
      {:else}
        <section class="picks" aria-label="Best bets">
          <p class="picks-note">Your strongest unwatched picks across every cluster.</p>
          <RecList recs={bestBets} {nodesById} onselectfilm={select} showCluster={homeLabel} />
        </section>
      {/if}

      <button class="reset" onclick={() => { clearFocus(); canvasRef?.resetView(); }}>Show whole map</button>
    </aside>

    {#if selected}
      <aside class="side-panel" aria-label="Selected film" style:--hue={communityColor(selected.community)}>
        <button class="close" onclick={() => select(null)} aria-label="Close">×</button>
        <h2 class="panel-title">{selected.label}</h2>
        <p class="facts">
          {[selected.year, watchedLine(selected)].filter(Boolean).join(". ")}.
          {#if selected.userRating}You rated it {selected.userRating} out of 10.{/if}
        </p>
        {#if selected.genres?.length}
          <p class="facts">{genreList(selected.genres, 4)}</p>
        {/if}
        {#if selected.community != null && profiles.get(selected.community)}
          <p class="in-cluster">
            Part of
            <button onclick={() => showCluster(selected.community!)}>{profiles.get(selected.community)!.label}</button>
          </p>
        {/if}
        <p class="links">
          {#if selected.slug}
            <a href={`https://trakt.tv/movies/${selected.slug}`} target="_blank" rel="noreferrer">Open on Trakt</a>
          {/if}
        </p>

        <h3>Keeps company with</h3>
        {#if neighbors.length}
          <ol class="neighbors">
            {#each neighbors as n (n.node.id)}
              <li>
                <button
                  onclick={() => select(n.node.id)}
                  onmouseenter={() => (hoverId = n.node.id)}
                  onmouseleave={() => (hoverId = null)}
                >
                  <span class="film">
                    <span class="dot" style:background={communityColor(n.node.community)}></span>
                    {n.node.label}
                    {#if n.node.year}<span class="year">{n.node.year}</span>{/if}
                  </span>
                  <span class="bar" style:--w={`${Math.round(n.weight * 100)}%`}></span>
                  <span class="share">{Math.round(n.weight * 100)}% overlap, {n.shared} shared</span>
                </button>
              </li>
            {/each}
          </ol>
        {:else}
          <p class="empty">No links at this threshold. Lower the overlap slider to see weaker ones.</p>
        {/if}
      </aside>
    {:else if openCluster}
      <ClusterPanel
        cluster={openCluster}
        {nodesById}
        evaluation={graph.evaluation}
        onselectfilm={select}
        onclose={() => (clusterId = null)}
      />
    {/if}

    {#if hoveredCluster && clusterHover && wide}
      <ClusterCard cluster={hoveredCluster} x={clusterHover.x} y={clusterHover.y} />
    {/if}
  {/if}
</main>

<style>
  main {
    position: fixed;
    inset: 0;
    overflow: hidden;
  }
  .stage {
    position: absolute;
    inset: 0;
  }

  .loading,
  .notice {
    position: absolute;
    inset: 0;
    display: grid;
    place-content: center;
    text-align: center;
    padding: 24px;
    color: var(--ink-dim);
  }
  .notice h1 {
    font: italic 400 2.25rem/1.1 var(--serif);
    color: var(--ink);
    margin: 0 0 0.5rem;
  }
  .notice p {
    margin: 0;
  }

  .rail {
    position: absolute;
    background: color-mix(in oklab, var(--panel) 88%, transparent);
    backdrop-filter: blur(10px);
    border: 1px solid var(--line);
    border-radius: 14px;
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .rail {
    top: 16px;
    left: 16px;
    bottom: 16px;
    width: 328px;
    padding: 22px 20px 18px;
    display: flex;
    flex-direction: column;
    gap: 18px;
  }
  .rail h1 {
    font: italic 400 2rem/1.05 var(--serif);
    margin: 0 0 0.5rem;
    letter-spacing: -0.005em;
  }
  .lede {
    margin: 0;
    color: var(--ink-dim);
    font-size: 0.875rem;
    line-height: 1.45;
  }

  .search {
    position: relative;
  }
  .search input {
    width: 100%;
    padding: 10px 12px;
    background: var(--field);
    color: var(--ink);
    border: 1px solid var(--line);
    border-radius: 8px;
    font: inherit;
  }
  .search input::placeholder {
    color: var(--ink-faint);
  }
  .results {
    position: absolute;
    z-index: 2;
    top: calc(100% + 4px);
    left: 0;
    right: 0;
    list-style: none;
    margin: 0;
    padding: 4px;
    background: var(--panel-raised);
    border: 1px solid var(--line);
    border-radius: 8px;
  }
  .results button {
    display: flex;
    align-items: baseline;
    gap: 8px;
    width: 100%;
    padding: 7px 8px;
    border-radius: 6px;
    text-align: left;
  }
  .results button:hover,
  .results button:focus-visible {
    background: var(--field);
  }
  .results .film {
    flex: 1;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .empty {
    color: var(--ink-dim);
    font-size: 0.875rem;
    margin: 8px 0 0;
  }

  .control label {
    display: block;
    font-size: 0.875rem;
    color: var(--ink-dim);
    margin-bottom: 6px;
  }
  .control output {
    color: var(--ink);
    font-variant-numeric: tabular-nums;
  }
  .control input {
    width: 100%;
    accent-color: var(--ink);
  }

  .clusters {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }
  .clusters ul {
    list-style: none;
    margin: 0 -8px 0 0;
    padding: 0 8px 0 0;
    overflow-y: auto;
    overscroll-behavior: contain;
  }
  .clusters button {
    display: grid;
    grid-template-columns: 10px 1fr auto;
    align-items: center;
    gap: 10px;
    width: 100%;
    padding: 7px 8px;
    border-radius: 7px;
    text-align: left;
    font-stretch: 85%;
  }
  .clusters button:hover,
  .clusters button.active {
    background: color-mix(in oklab, var(--hue) 14%, transparent);
  }
  .clusters .dot {
    background: var(--hue);
    box-shadow: 0 0 8px var(--hue);
  }
  .clusters .name {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font: italic 1.0625rem/1.2 var(--serif);
  }
  .tabs {
    display: flex;
    gap: 4px;
    border-bottom: 1px solid var(--line);
  }
  .tabs button {
    padding: 6px 10px 8px;
    margin-bottom: -1px;
    font-size: 0.875rem;
    color: var(--ink-dim);
    border-bottom: 2px solid transparent;
  }
  .tabs button[aria-selected="true"] {
    color: var(--ink);
    border-bottom-color: var(--ink);
  }
  .picks {
    flex: 1;
    min-height: 0;
    overflow-y: auto;
    overscroll-behavior: contain;
    margin-right: -8px;
    padding-right: 8px;
  }
  .picks-note {
    margin: 0 0 12px;
    font-size: 0.8125rem;
    color: var(--ink-dim);
  }
  .in-cluster {
    margin: 0 0 10px;
    font-size: 0.875rem;
    color: var(--ink-dim);
  }
  .in-cluster button {
    font: italic 1.0625rem var(--serif);
    color: var(--hue);
    text-decoration: underline;
    text-decoration-color: color-mix(in oklab, var(--hue) 40%, transparent);
    text-underline-offset: 3px;
  }
  .count {
    color: var(--ink-faint);
    font-size: 0.8125rem;
    font-variant-numeric: tabular-nums;
  }

  .reset {
    align-self: flex-start;
    color: var(--ink-dim);
    font-size: 0.875rem;
    text-decoration: underline;
    text-underline-offset: 3px;
    text-decoration-color: var(--line);
  }
  .reset:hover {
    color: var(--ink);
  }

  .dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .year {
    color: var(--ink-faint);
    font-size: 0.8125rem;
    font-variant-numeric: tabular-nums;
  }

  .facts {
    color: var(--ink-dim);
    font-size: 0.875rem;
    margin: 0 0 10px;
  }
  .links {
    display: flex;
    gap: 16px;
    margin: 0 0 24px;
    font-size: 0.875rem;
  }
  .links a {
    color: var(--hue);
    text-decoration: underline;
    text-underline-offset: 3px;
    text-decoration-color: color-mix(in oklab, var(--hue) 40%, transparent);
  }
  .neighbors {
    list-style: none;
    margin: 0;
    padding: 0;
  }
  .neighbors button {
    display: grid;
    gap: 4px;
    width: 100%;
    padding: 8px 6px;
    border-radius: 7px;
    text-align: left;
  }
  .neighbors button:hover {
    background: var(--field);
  }
  .neighbors .film {
    display: flex;
    align-items: baseline;
    gap: 8px;
    font-size: 0.9375rem;
  }
  .neighbors .film .dot {
    transform: translateY(-1px);
  }
  .bar {
    height: 3px;
    border-radius: 2px;
    background: linear-gradient(var(--hue), var(--hue)) no-repeat 0 0 / var(--w) 100%, var(--line);
  }
  .share {
    color: var(--ink-faint);
    font-size: 0.75rem;
    font-variant-numeric: tabular-nums;
  }

  @media (max-width: 759px) {
    .rail {
      top: 12px;
      left: 12px;
      right: 12px;
      bottom: auto;
      width: auto;
      max-height: calc(100dvh - 24px);
      padding: 14px 14px 12px;
      gap: 10px;
    }
    .rail h1 {
      font-size: 1.5rem;
    }
    .lede {
      display: none;
    }
    .reset {
      display: none;
    }
    .clusters {
      max-height: 30dvh;
    }
  }
</style>
