<script lang="ts">
  import type { ClusterProfile } from "./graph";
  import { communityColor } from "./palette";
  import { era, genreName, pct } from "./format";

  let { cluster, x, y }: { cluster: ClusterProfile; x: number; y: number } = $props();

  // Keep the card on screen.
  let card = $state<HTMLDivElement>();
  const left = $derived(Math.max(12, Math.min(x - 160, (typeof innerWidth === "number" ? innerWidth : 1200) - 332)));
  const top = $derived(Math.min(y + 8, (typeof innerHeight === "number" ? innerHeight : 800) - (card?.offsetHeight ?? 220) - 12));
</script>

<div class="card" bind:this={card} role="tooltip" style:left={`${left}px`} style:top={`${top}px`} style:--hue={communityColor(cluster.id)}>
  <p class="name">{cluster.label}</p>
  {#if cluster.summary}
    <p class="summary">{cluster.summary}</p>
  {/if}
  <dl>
    <dt>Films</dt>
    <dd>{cluster.size}{#if era(cluster)}, mostly {era(cluster)}{/if}</dd>
    {#if cluster.genres.length}
      <dt>Genres</dt>
      <dd>{cluster.genres.slice(0, 3).map((g) => `${genreName(g.name)} ${pct(g.share)}`).join(", ")}</dd>
    {/if}
    {#if cluster.themes?.length}
      <dt>Themes</dt>
      <dd>{cluster.themes.join(", ")}</dd>
    {/if}
  </dl>
  <p class="hint">Click to see what defines it and what to watch next.</p>
</div>

<style>
  .card {
    position: fixed;
    z-index: 20;
    width: 320px;
    padding: 14px 16px 12px;
    background: var(--panel-raised);
    border: 1px solid var(--line);
    border-top: 3px solid var(--hue);
    border-radius: 10px;
    box-shadow: 0 12px 32px rgba(5, 8, 20, 0.5);
    pointer-events: none;
  }
  .name {
    font: italic 400 1.5rem/1.1 var(--serif);
    margin: 0 0 6px;
    color: var(--hue);
  }
  .summary {
    margin: 0 0 10px;
    font-size: 0.875rem;
    line-height: 1.45;
  }
  dl {
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 3px 12px;
    margin: 0 0 8px;
    font-size: 0.8125rem;
  }
  dt {
    color: var(--ink-faint);
  }
  dd {
    margin: 0;
    color: var(--ink-dim);
  }
  .hint {
    margin: 0;
    font-size: 0.75rem;
    color: var(--ink-faint);
  }
</style>
