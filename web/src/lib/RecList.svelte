<script lang="ts">
  import type { GraphNode, Recommendation } from "./graph";
  import { genreList, pct, tier } from "./format";

  let {
    recs,
    nodesById,
    onselectfilm,
    showCluster = null,
  }: {
    recs: Recommendation[];
    nodesById: Map<number, GraphNode>;
    onselectfilm: (id: number) => void;
    showCluster?: ((r: Recommendation) => { label: string; color: string } | null) | null;
  } = $props();

  let open = $state<number | null>(null);
</script>

<ol class="recs">
  {#each recs as r (r.id)}
    {@const t = tier(r)}
    {@const because = r.because.map((id) => nodesById.get(id)).filter((n) => n != null)}
    {@const home = showCluster?.(r)}
    <li>
      <div class="poster">
        {#if r.poster}
          <img src={r.poster} alt="" referrerpolicy="no-referrer" onerror={(e) => ((e.currentTarget as HTMLImageElement).style.display = "none")} />
        {/if}
      </div>
      <div class="body">
        <p class="title">
          {#if r.slug}
            <a href={`https://trakt.tv/movies/${r.slug}`} target="_blank" rel="noreferrer">{r.title}</a>
          {:else}{r.title}{/if}
          {#if r.year}<span class="year">{r.year}</span>{/if}
        </p>
        <p class="meta">
          <span class={`tier t${t.level}`} title={r.confidence != null
            ? `In a hold-out test, ${pct(r.confidence)} of titles this connected to your history were films you had watched.`
            : "Run trakt-ify evaluate to measure confidence."}>{t.label}{#if r.confidence != null}, {pct(r.confidence)}{/if}</span>
          {#if r.communityRating}<span>Trakt {r.communityRating.toFixed(1)}</span>{/if}
          {#if r.genres?.length}<span>{genreList(r.genres, 2)}</span>{/if}
          {#if r.onWatchlist}<span class="watchlist">On your watchlist</span>{/if}
        </p>
        {#if home}
          <p class="home"><span class="dot" style:background={home.color}></span>{home.label}</p>
        {/if}
        <p class="why">
          {r.support} of your films point here, including
          {#each because.slice(0, 3) as n, i (n.id)}
            <button class="film-link" onclick={() => onselectfilm(n.id)}>{n.label}</button>{i < Math.min(3, because.length) - 1 ? ", " : ""}
          {/each}.
        </p>
        {#if r.overview}
          <button class="more" aria-expanded={open === r.id} onclick={() => (open = open === r.id ? null : r.id)}>
            {open === r.id ? "Hide synopsis" : "Synopsis"}
          </button>
          {#if open === r.id}<p class="overview">{r.overview}</p>{/if}
        {/if}
      </div>
    </li>
  {/each}
</ol>

<style>
  .recs {
    list-style: none;
    margin: 0;
    padding: 0;
    display: grid;
    gap: 14px;
  }
  li {
    display: grid;
    grid-template-columns: 52px 1fr;
    gap: 12px;
  }
  .poster {
    width: 52px;
    aspect-ratio: 2 / 3;
    border-radius: 4px;
    background: var(--field);
    overflow: hidden;
  }
  .poster img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .body {
    min-width: 0;
  }
  .title {
    margin: 0 0 3px;
    font-size: 0.9375rem;
    line-height: 1.25;
  }
  .title a {
    color: var(--ink);
    text-decoration: none;
  }
  .title a:hover {
    text-decoration: underline;
    text-underline-offset: 3px;
  }
  .year {
    color: var(--ink-faint);
    font-size: 0.8125rem;
    margin-left: 4px;
  }
  .meta {
    display: flex;
    flex-wrap: wrap;
    gap: 2px 10px;
    margin: 0 0 4px;
    font-size: 0.75rem;
    color: var(--ink-faint);
  }
  .tier {
    color: var(--ink-dim);
  }
  .tier.t3 {
    color: var(--hue, var(--ink));
    font-weight: 600;
  }
  .tier.t2 {
    color: var(--ink);
  }
  .watchlist {
    color: var(--ink);
  }
  .home {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 3px;
    font: italic 0.875rem/1.2 var(--serif);
    color: var(--ink-dim);
  }
  .dot {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    flex: none;
  }
  .why {
    margin: 0;
    font-size: 0.8125rem;
    line-height: 1.4;
    color: var(--ink-dim);
  }
  .film-link {
    color: var(--ink);
    text-decoration: underline;
    text-decoration-color: var(--line);
    text-underline-offset: 2px;
  }
  .film-link:hover {
    text-decoration-color: var(--ink);
  }
  .more {
    margin-top: 4px;
    font-size: 0.75rem;
    color: var(--ink-faint);
    text-decoration: underline;
    text-underline-offset: 2px;
  }
  .overview {
    margin: 6px 0 0;
    font-size: 0.8125rem;
    line-height: 1.45;
    color: var(--ink-dim);
  }
</style>
