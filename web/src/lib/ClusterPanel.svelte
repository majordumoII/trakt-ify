<script lang="ts">
  import type { ClusterProfile, Evaluation, GraphNode } from "./graph";
  import { communityColor } from "./palette";
  import { era, genreName, pct } from "./format";
  import RecList from "./RecList.svelte";

  let {
    cluster,
    nodesById,
    evaluation,
    onselectfilm,
    onclose,
  }: {
    cluster: ClusterProfile;
    nodesById: Map<number, GraphNode>;
    evaluation: Evaluation | null | undefined;
    onselectfilm: (id: number) => void;
    onclose: () => void;
  } = $props();

  const anchors = $derived(cluster.anchors.map((id) => nodesById.get(id)).filter((n) => n != null));
  const topBucket = $derived(evaluation?.calibration.at(-1));
</script>

<aside class="side-panel" aria-label="Cluster" style:--hue={communityColor(cluster.id)}>
  <button class="close" onclick={onclose} aria-label="Close">×</button>
  <h2 class="panel-title cluster-name">{cluster.label}</h2>
  {#if cluster.summary}
    <p class="summary">{cluster.summary}</p>
  {:else}
    <p class="note">Named from its genres and era. Run <code>trakt-ify describe</code> for a written description.</p>
  {/if}
  {#if cluster.themes?.length}
    <p class="themes">{cluster.themes.join(", ")}</p>
  {/if}

  <h3>What it’s made of</h3>
  <ul class="genres">
    {#each cluster.genres as g (g.name)}
      <li>
        <span class="g-name">{genreName(g.name)}</span>
        <span class="bar" style:--w={pct(g.share)}></span>
        <span class="g-share">{pct(g.share)}</span>
      </li>
    {/each}
  </ul>
  <p class="facts">
    {cluster.size} films{#if era(cluster)}, the middle half released {era(cluster)}{/if}.
    {#if cluster.avgUserRating != null}
      You rated {cluster.ratedCount} of them, averaging {cluster.avgUserRating} out of 10.
    {/if}
  </p>

  <h3>Defining films</h3>
  <p class="anchors">
    {#each anchors as n, i (n.id)}
      <button class="film-link" onclick={() => onselectfilm(n.id)}>{n.label}</button>{i < anchors.length - 1 ? ", " : ""}
    {/each}
  </p>

  <h3>Watch next from here</h3>
  {#if cluster.recommendations?.length}
    <RecList recs={cluster.recommendations} {nodesById} {onselectfilm} />
  {:else}
    <p class="note">Nothing unwatched points strongly enough at this cluster yet.</p>
  {/if}

  <details class="method">
    <summary>How picks are chosen</summary>
    <p>
      Each pick is a film you haven’t logged that Trakt lists as related to many of your watched films. Films you
      rated 8 or higher count double; films you rated 5 or lower count a quarter. Poorly rated or very obscure titles
      are dropped. A pick appears under the cluster that holds most of the films pointing to it.
    </p>
    {#if evaluation}
      <p>
        To check this, {pct(evaluation.holdoutShare)} of your history was hidden at a time and the picks recomputed.
        {pct(evaluation.topKHitRate)} of the top {evaluation.k} were films you had in fact watched{#if topBucket}, rising to
        {pct(topBucket.hitRate)} for the most connected titles{/if}. That percentage is shown on each pick. It undercounts:
        a film you’d love but haven’t logged counts as a miss.
      </p>
    {:else}
      <p>Run <code>trakt-ify evaluate</code> to measure how often picks like these were films you watched.</p>
    {/if}
  </details>
</aside>

<style>
  .cluster-name {
    color: var(--hue);
  }
  .summary {
    margin: 0 0 8px;
    line-height: 1.5;
  }
  .themes {
    margin: 0 0 4px;
    font-size: 0.8125rem;
    color: var(--ink-dim);
  }
  .note {
    margin: 0 0 8px;
    font-size: 0.8125rem;
    color: var(--ink-faint);
  }
  code {
    font-size: 0.8em;
    color: var(--ink-dim);
  }
  .genres {
    list-style: none;
    margin: 0 0 8px;
    padding: 0;
    display: grid;
    gap: 5px;
  }
  .genres li {
    display: grid;
    grid-template-columns: 96px 1fr 36px;
    align-items: center;
    gap: 10px;
    font-size: 0.8125rem;
  }
  .bar {
    height: 4px;
    border-radius: 2px;
    background: linear-gradient(var(--hue), var(--hue)) no-repeat 0 0 / var(--w) 100%, var(--line);
  }
  .g-share {
    text-align: right;
    color: var(--ink-faint);
    font-variant-numeric: tabular-nums;
  }
  .facts {
    margin: 0;
    font-size: 0.8125rem;
    color: var(--ink-dim);
    line-height: 1.45;
  }
  .anchors {
    margin: 0;
    font-size: 0.875rem;
    line-height: 1.6;
  }
  .film-link {
    text-decoration: underline;
    text-decoration-color: var(--line);
    text-underline-offset: 2px;
  }
  .film-link:hover {
    text-decoration-color: var(--ink);
  }
  .method {
    margin-top: 22px;
    font-size: 0.8125rem;
    color: var(--ink-dim);
    line-height: 1.5;
  }
  .method summary {
    cursor: pointer;
    color: var(--ink);
  }
  .method p {
    margin: 8px 0 0;
  }
</style>
