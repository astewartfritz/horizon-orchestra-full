/**
 * CouncilStream — SSE client for GET /api/v1/council/stream
 * Drop in gui/js/ and include with <script src="js/council_stream.js"></script>
 */
class CouncilStream {
  constructor({ prompt, models, synthesisModel, fastPath, onEvent, onDone, onError }) {
    this.prompt = prompt;
    this.models = models || [];
    this.synthesisModel = synthesisModel || '';
    this.fastPath = fastPath || false;
    this.onEvent = onEvent;
    this.onDone = onDone;
    this.onError = onError;
    this._es = null;
    this._buffer = '';
  }

  start() {
    const params = new URLSearchParams({ prompt: this.prompt });
    if (this.models.length) params.set('models', this.models.join(','));
    if (this.synthesisModel) params.set('synthesis_model', this.synthesisModel);
    if (this.fastPath) params.set('fast_path', 'true');

    this._es = new EventSource('/api/v1/council/stream?' + params);

    this._es.onmessage = (e) => {
      if (e.data === '[DONE]') {
        this._es.close();
        if (this.onDone) this.onDone(this._buffer);
        return;
      }
      try {
        const evt = JSON.parse(e.data);
        if (this.onEvent) this.onEvent(evt);
        if (evt.type === 'synthesis_token') this._buffer += evt.text;
        if (evt.type === 'synthesis_complete') {
          if (this.onDone) this.onDone(evt.result || this._buffer);
        }
      } catch (_) {}
    };

    this._es.onerror = () => {
      this._es.close();
      if (this.onError) this.onError('Connection lost');
    };
  }

  stop() { if (this._es) this._es.close(); }
}

class SpecDecStream {
  constructor({ prompt, draftModel, verifyModel, maxTokens, onToken, onDone, onError }) {
    this.prompt = prompt;
    this.draftModel = draftModel || 'brain2';
    this.verifyModel = verifyModel || 'brain4';
    this.maxTokens = maxTokens || 512;
    this.onToken = onToken;
    this.onDone = onDone;
    this.onError = onError;
    this._es = null;
  }

  start() {
    const params = new URLSearchParams({
      prompt: this.prompt,
      draft_model: this.draftModel,
      verify_model: this.verifyModel,
      max_tokens: this.maxTokens,
    });

    this._es = new EventSource('/api/v1/specdec/stream?' + params);

    this._es.onmessage = (e) => {
      if (e.data === '[DONE]') { this._es.close(); return; }
      try {
        const evt = JSON.parse(e.data);
        if (evt.type === 'token' && this.onToken) this.onToken(evt.text);
        if (evt.type === 'done') {
          this._es.close();
          if (this.onDone) this.onDone(evt);
        }
      } catch (_) {}
    };

    this._es.onerror = () => {
      this._es.close();
      if (this.onError) this.onError('Connection lost');
    };
  }

  stop() { if (this._es) this._es.close(); }
}
