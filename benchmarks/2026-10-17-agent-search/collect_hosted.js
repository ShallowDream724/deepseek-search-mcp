/**
 * Run inside an authorized host that exposes the actual tools object.
 * save(record) must persist each record as raw/{provider}-{case_id}.json.
 * Keep an independent directory per run. Never overwrite the frozen baseline.
 */
async function collectHosted(tools, cases, save, provider, concurrency = 4) {
  if (!['native', 'anysearch', 'anysearch_general'].includes(provider)) {
    throw new Error('Unsupported provider');
  }
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 4) {
    throw new Error('concurrency must be 1–4');
  }
  let cursor = 0;
  async function worker() {
    while (cursor < cases.length) {
      const item = cases[cursor++];
      const request = provider === 'native'
        ? {search_query: [{q: item.query}], response_length: 'long'}
        : provider === 'anysearch_general'
          ? {query: item.query, max_results: 5}
          : item.anysearch;
      const started = Date.now();
      const record = {provider, case_id: item.id, query: item.query,
        started_at: new Date(started).toISOString(), request};
      try {
        record.response = provider === 'native'
          ? await tools.web__run(request)
          : await tools.mcp__anysearch__search(request);
      } catch (error) {
        record.transport_error = error?.name || 'Error';
      }
      record.elapsed_ms = Date.now() - started;
      await save(record);
    }
  }
  await Promise.all(Array.from({length: concurrency}, worker));
}

async function collectHostedFetch(tools, cases, save, provider, concurrency = 4) {
  if (!['native', 'anysearch'].includes(provider)) throw new Error('Unsupported provider');
  if (!Number.isInteger(concurrency) || concurrency < 1 || concurrency > 4) throw new Error('concurrency must be 1–4');
  let cursor = 0;
  async function worker() {
    while (cursor < cases.length) {
      const item = cases[cursor++];
      const started = Date.now();
      const record = {provider, case_id: item.id, url: item.url, started_at: new Date(started).toISOString()};
      try {
        record.response = provider === 'native'
          ? await tools.web__run({open:[{ref_id:item.url}], response_length:'long'})
          : await tools.mcp__anysearch__extract({url:item.url});
      } catch (error) {
        record.transport_error = error?.name || 'Error';
      }
      record.elapsed_ms = Date.now() - started;
      await save(record);
    }
  }
  await Promise.all(Array.from({length: concurrency}, worker));
}
