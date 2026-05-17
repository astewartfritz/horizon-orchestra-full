/**
 * CouncilPanel — vanilla JS component for live model council deliberation UI
 * Drop in gui/js/ and include AFTER council_stream.js
 *
 * Usage:
 *   const panel = new CouncilPanel(document.getElementById('response-area'));
 *   panel.addMember('brain4');
 *   panel.memberComplete('brain4', 0.87, 'The answer is...');
 *   panel.synthesisStart('claude-sonnet-4.6');
 *   panel.synthesisToken('Hello ');
 *   panel.synthesisComplete(true, 0.91, 0.84);
 */
class CouncilPanel {
  constructor(containerEl) {
    this.container = containerEl;
    this._memberEls = {};
    this._synthesisTextEl = null;
    this._render();
  }

  _render() {
    this.container.innerHTML = `
      <div class="council-panel">
        <div class="council-header">
          <span class="council-icon">&#9889;</span>
          <span class="council-title">Model Council</span>
          <span class="council-status" id="cp-status">Deliberating...</span>
        </div>
        <div class="council-members" id="cp-members"></div>
        <div class="council-synthesis hidden" id="cp-synthesis">
          <div class="synthesis-header">
            <span class="synthesis-label">Synthesizing via</span>
            <span class="synthesis-model" id="cp-synth-model"></span>
          </div>
          <div class="synthesis-text" id="cp-synth-text"></div>
          <div class="synthesis-meta hidden" id="cp-synth-meta"></div>
        </div>
        <div class="specdec-panel hidden" id="cp-specdec">
          <div class="specdec-header">Speculative Decoding</div>
          <div class="specdec-bar-wrap"><div class="specdec-bar" id="cp-specdec-bar" style="width:0%"></div></div>
          <div class="specdec-stats" id="cp-specdec-stats"></div>
        </div>
      </div>`;
  }

  addMember(modelName) {
    const id = 'cp-m-' + modelName.replace(/[^a-z0-9]/gi, '-');
    const el = document.createElement('div');
    el.className = 'council-member pending';
    el.id = id;
    el.innerHTML = `<span class="member-name">${modelName}</span>
      <span class="member-spinner">&#9676;</span>
      <span class="member-score hidden"></span>`;
    this.container.querySelector('#cp-members').appendChild(el);
    this._memberEls[modelName] = el;
  }

  memberComplete(modelName, score, preview) {
    const el = this._memberEls[modelName];
    if (!el) return;
    el.classList.remove('pending');
    el.classList.add('done');
    const spinner = el.querySelector('.member-spinner');
    if (spinner) spinner.remove();
    const scoreEl = el.querySelector('.member-score');
    scoreEl.textContent = Math.round(score * 100) + '%';
    scoreEl.classList.remove('hidden');
    if (preview) {
      const p = document.createElement('div');
      p.className = 'member-preview';
      p.textContent = preview;
      el.appendChild(p);
    }
  }

  synthesisStart(modelName) {
    const panel = this.container.querySelector('#cp-synthesis');
    panel.classList.remove('hidden');
    this.container.querySelector('#cp-synth-model').textContent = modelName;
    this._synthesisTextEl = this.container.querySelector('#cp-synth-text');
    this._synthesisTextEl.textContent = '';
  }

  synthesisToken(text) {
    if (this._synthesisTextEl) this._synthesisTextEl.textContent += text;
  }

  synthesisComplete(qualityGatePassed, synthesisScore, bestIndividualScore) {
    this.container.querySelector('#cp-status').textContent = 'Done';
    const meta = this.container.querySelector('#cp-synth-meta');
    meta.classList.remove('hidden');
    const badgeClass = qualityGatePassed ? 'gate-pass' : 'gate-fallback';
    const badgeText = qualityGatePassed ? '&#10003; Synthesis' : '&#9888; Best Individual';
    meta.innerHTML = `<span class="gate-badge ${badgeClass}">${badgeText}</span>
      <span class="score-detail">synthesis ${Math.round(synthesisScore*100)}% vs best ${Math.round(bestIndividualScore*100)}%</span>`;
  }

  showSpecDecBar(acceptanceRate, stats) {
    const panel = this.container.querySelector('#cp-specdec');
    panel.classList.remove('hidden');
    this.container.querySelector('#cp-specdec-bar').style.width = Math.round(acceptanceRate * 100) + '%';
    this.container.querySelector('#cp-specdec-stats').textContent =
      Math.round(acceptanceRate * 100) + '% accepted · ' + (stats.accepted_tokens||0) + ' tokens · ' + (stats.wall_time||0) + 's';
  }
}

/**
 * Convenience: wire CouncilPanel into an existing chat UI.
 *
 * sendCouncilMessage(prompt, responseContainer)
 *   - Creates a CouncilPanel inside responseContainer
 *   - Connects to /api/v1/council/stream
 *   - Returns the panel instance
 */
function sendCouncilMessage(prompt, responseContainer) {
  const panel = new CouncilPanel(responseContainer);
  ['brain4', 'kimi-k2.5', 'brain3'].forEach(m => panel.addMember(m));

  const stream = new CouncilStream({
    prompt,
    onEvent(evt) {
      if (evt.type === 'member_complete') {
        panel.memberComplete(evt.model, evt.score || 0, evt.preview || '');
      } else if (evt.type === 'synthesis_start') {
        panel.synthesisStart(evt.synthesis_model || 'synthesizer');
      } else if (evt.type === 'synthesis_token') {
        panel.synthesisToken(evt.text);
      } else if (evt.type === 'synthesis_complete') {
        panel.synthesisComplete(evt.quality_gate_passed, evt.synthesis_score || 0, evt.best_individual_score || 0);
      }
    },
    onDone() {},
    onError(err) {
      responseContainer.innerHTML += '<div class="council-error">' + err + '</div>';
    }
  });

  stream.start();
  return panel;
}
