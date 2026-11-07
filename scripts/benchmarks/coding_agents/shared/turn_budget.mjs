export default function turnBudget(pi) {
  const maximum = Number(process.env.HARNESS_BENCHMARK_MAX_TURNS);
  console.error(`[BENCHMARK] turn limit: ${maximum}`);
  let turns = 0;
  pi.on("turn_start", (_event, ctx) => {
    if (++turns > maximum) {
      console.error("[BENCHMARK] turn budget exhausted");
      ctx.abort();
    } else {
      console.error(`[BENCHMARK] turn ${turns}/${maximum}`);
    }
  });
}
