/* EquitableT2L portal — progressive enhancement only.
   Every page works as plain HTML; this file adds the dependent topic
   selects, the live chat socket, and busy states on submit. */
(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const escapeHtml = (text) => {
    const node = document.createElement('div');
    node.textContent = text;
    return node.innerHTML;
  };
  const hasKeyboard = () => window.matchMedia('(hover: hover) and (pointer: fine)').matches;

  /* ---------------------------------------------------------------------
     Submit buttons show a busy state so a slow response never looks stuck.
     --------------------------------------------------------------------- */
  document.querySelectorAll('[data-busy-form]').forEach((form) => {
    form.addEventListener('submit', () => {
      const button = $('button[type="submit"]', form);
      if (!button || button.disabled) return;
      button.dataset.label = button.innerHTML;
      button.disabled = true;
      button.textContent = 'Please wait…';
      form.setAttribute('aria-busy', 'true');
    });
  });

  /* ---------------------------------------------------------------------
     Topic selection: subject → topic → subtopic, driven by the taxonomy
     embedded in the page.
     --------------------------------------------------------------------- */
  const selectionForm = $('[data-selection-form]');
  if (selectionForm) {
    let taxonomy = {};
    try {
      taxonomy = JSON.parse($('#taxonomy-data')?.textContent || '{}');
    } catch (_) {
      taxonomy = {};
    }

    const subject = $('[data-select="subject"]', selectionForm);
    const topic = $('[data-select="topic"]', selectionForm);
    const subtopic = $('[data-select="subtopic"]', selectionForm);
    const model = $('[data-select="model"]', selectionForm);
    const submit = $('button[type="submit"]', selectionForm);
    const summary = $('[data-selection-summary]', selectionForm);
    const modelSummary = $('[data-selection-model]', selectionForm);

    const entries = (value) => (Array.isArray(value)
      ? value.map((item) => (typeof item === 'string' ? { id: item, name: item } : item))
      : Object.entries(value || {}).map(([id, item]) => (typeof item === 'string' ? { id, name: item } : { id, ...item })));

    const option = (item) => `<option value="${escapeHtml(String(item.id ?? item.value ?? item.name))}">${escapeHtml(String(item.name ?? item.label ?? item.id))}</option>`;

    const fill = (select, values, prompt) => {
      const items = entries(values);
      select.innerHTML = `<option value="">${prompt}</option>${items.map(option).join('')}`;
      select.disabled = !items.length;
    };

    const selectedLabel = (select) => select.selectedOptions[0]?.textContent || '';

    const update = () => {
      const ready = [model, subject, topic, subtopic].every((el) => el.value);
      submit.disabled = !ready;
      summary.textContent = ready
        ? `${selectedLabel(subject)} · ${selectedLabel(topic)} · ${selectedLabel(subtopic)}`
        : 'Complete the choices above';
      if (modelSummary) {
        modelSummary.textContent = model.value ? `Taught to ${selectedLabel(model)}` : '';
        modelSummary.hidden = !model.value;
      }
    };

    const subjectNode = () => taxonomy[subject.value]
      || entries(taxonomy).find((item) => String(item.id) === subject.value)
      || {};

    subject.addEventListener('change', () => {
      const node = subjectNode();
      fill(topic, node.topics || node, 'Select a topic');
      fill(subtopic, [], 'Select a topic first');
      update();
    });

    topic.addEventListener('change', () => {
      const root = subjectNode();
      const topics = root.topics || root;
      const node = topics[topic.value]
        || entries(topics).find((item) => String(item.id) === topic.value)
        || {};
      fill(subtopic, node.subtopics || node.items || [], 'Select a subtopic');
      update();
    });

    [model, subtopic].forEach((el) => el.addEventListener('change', update));
    update();
  }

  /* ---------------------------------------------------------------------
     Chat session.
     --------------------------------------------------------------------- */
  const chat = $('[data-chat]');
  if (chat) {
    const MAX_TURNS = Number(chat.dataset.maxTurns) || 6;
    const sessionId = chat.dataset.sessionId;

    const form = $('[data-chat-form]', chat);
    const input = $('[data-chat-input]', chat);
    const messages = $('[data-messages]', chat);
    const typing = $('[data-typing]', chat);
    const typingLabel = $('.typing-label', typing);
    const send = $('button[type="submit"]', form);
    const current = $('[data-turn-current]', chat);
    const bar = $('[data-progress-bar]', chat);
    const track = $('[data-progress-track]', chat);
    const completePanel = $('[data-chat-complete]', chat);
    const errorBox = $('[data-chat-error]', chat);
    const connection = $('[data-connection-status]');
    const connectionLabel = $('[data-connection-label]');
    const characterCount = $('[data-character-count]', chat);
    const micButton = $('[data-mic-button]', chat);
    const micStatus = $('[data-mic-status]', chat);
    const draftKey = `teach2learn-draft-${sessionId}`;

    let turn = Number(chat.dataset.turn) || 0;
    let finished = chat.dataset.complete === 'true';
    let pending = false;
    let socket = null;

    const scroll = () => { messages.scrollTop = messages.scrollHeight; };

    const roleLabel = (role) => (role === 'user' ? 'You · teacher' : 'AI student');
    const turnLabel = (value) => (value > 0 ? `Turn ${value} · up to ${MAX_TURNS}` : 'Opening question');

    const add = (role, content, messageTurn) => {
      const article = document.createElement('article');
      article.className = `message message-${role}`;
      article.innerHTML = `<p class="message-author">`
        + `<span class="message-role">${escapeHtml(roleLabel(role))}</span>`
        + `<span class="message-turn">${escapeHtml(turnLabel(Number(messageTurn) || 0))}</span>`
        + `</p><div class="message-body">${escapeHtml(content)}</div>`;
      messages.insertBefore(article, typing);
      scroll();
    };

    const showError = (text) => {
      if (!errorBox) { window.alert(text); return; }
      errorBox.textContent = text;
      errorBox.hidden = false;
    };

    const clearError = () => {
      if (!errorBox) return;
      errorBox.hidden = true;
      errorBox.textContent = '';
    };

    const setConnection = (state, label) => {
      if (!connection) return;
      connection.dataset.state = state;
      if (connectionLabel) connectionLabel.textContent = label;
    };

    const progress = () => {
      if (current) current.textContent = String(turn);
      if (bar) bar.style.width = `${Math.min(100, (turn / MAX_TURNS) * 100)}%`;
      if (track) track.setAttribute('aria-valuenow', String(turn));
    };

    /* The conversation ends on the page rather than redirecting mid-read, so
       the participant can see the student's final reply before moving on. */
    const finish = () => {
      finished = true;
      if (form) form.hidden = true;
      if (completePanel) {
        completePanel.hidden = false;
        $('[data-complete-link]', completePanel)?.focus({ preventScroll: true });
      }
      setConnection('online', 'Session complete');
      if (socket && socket.readyState === WebSocket.OPEN) socket.close(1000);
      scroll();
    };

    const settle = () => {
      pending = false;
      typing.hidden = true;
      send.disabled = false;
      input.disabled = false;
      if (typingLabel) typingLabel.textContent = 'AI learner is thinking';
      if (hasKeyboard()) input.focus();
      scroll();
    };

    const onMessage = ({ data }) => {
      let payload;
      try {
        payload = JSON.parse(data);
      } catch (_) {
        payload = { content: data };
      }
      if (payload.error) {
        settle();
        showError(payload.error);
        return;
      }
      if (payload.status === 'queued') {
        const position = Number(payload.queue_position || 1);
        setConnection('connecting', position > 1 ? `Waiting for GPU · ${position} ahead` : 'Waiting for GPU…');
        if (typingLabel) typingLabel.textContent = position > 1
          ? `Waiting for the AI learner · ${position} ahead`
          : 'Preparing the AI learner';
        return;
      }
      if (payload.status === 'evaluating') {
        setConnection('connecting', 'Checking understanding…');
        if (typingLabel) typingLabel.textContent = 'Checking understanding in the background';
      }
      if (payload.content || payload.message) {
        add('assistant', payload.content || payload.message, payload.turn ?? turn + 1);
      }
      if (payload.done !== false) {
        turn = Number(payload.turn ?? turn + 1);
        settle();
        progress();
        if (payload.complete || turn >= MAX_TURNS) finish();
      }
    };

    const socketUrl = () => {
      const raw = chat.dataset.wsUrl;
      if (raw.startsWith('ws')) return raw;
      return `${location.protocol === 'https:' ? 'wss:' : 'ws:'}//${location.host}${raw}`;
    };

    const openSocket = () => {
      if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        return socket;
      }
      socket = new WebSocket(socketUrl());
      setConnection('connecting', 'Connecting…');
      socket.addEventListener('open', () => setConnection('online', 'Session in progress'));
      socket.addEventListener('message', onMessage);
      socket.addEventListener('close', () => {
        if (finished || turn >= MAX_TURNS) return;
        setConnection('offline', 'Reconnecting on next send');
        if (pending) {
          settle();
          showError('The connection dropped before the student replied. Send your explanation again.');
        }
      });
      return socket;
    };

    form.addEventListener('submit', (event) => {
      event.preventDefault();
      const value = input.value.trim();
      if (!value || pending || finished || turn >= MAX_TURNS) return;

      const active = openSocket();
      if (active.readyState !== WebSocket.OPEN) {
        active.addEventListener('open', () => form.requestSubmit(), { once: true });
        return;
      }

      clearError();
      pending = true;
      add('user', value, turn + 1);
      input.value = '';
      try { sessionStorage.removeItem(draftKey); } catch (_) { /* Storage can be disabled. */ }
      input.style.height = 'auto';
      input.disabled = true;
      send.disabled = true;
      typing.hidden = false;
      scroll();
      active.send(JSON.stringify({ message: value, session_id: sessionId, turn: turn + 1 }));
    });

    /* Enter sends only where there is a physical keyboard; on touch it has to
       stay a newline, otherwise a long explanation cannot be written. */
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' && !event.shiftKey && hasKeyboard()) {
        event.preventDefault();
        form.requestSubmit();
      }
    });

    const autosize = () => {
      input.style.height = 'auto';
      input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
      if (characterCount) {
        const length = input.value.length;
        characterCount.textContent = `${length.toLocaleString()} / 2,000`;
        characterCount.dataset.nearLimit = String(length >= 1800);
      }
    };
    input.addEventListener('input', () => {
      autosize();
      try { sessionStorage.setItem(draftKey, input.value); } catch (_) { /* Storage can be disabled. */ }
    });

    /* Voice dictation: record with MediaRecorder, upload the clip once the
       participant stops it, and append whatever the server transcribes. */
    if (micButton) {
      const canRecord = !!(navigator.mediaDevices?.getUserMedia && window.MediaRecorder);
      if (!canRecord) {
        micButton.hidden = true;
      } else {
        let recorder = null;
        let chunks = [];
        let recording = false;

        const setMicStatus = (text) => {
          if (!micStatus) return;
          micStatus.textContent = text;
          micStatus.hidden = !text;
        };

        const setMicState = (state) => {
          micButton.dataset.state = state;
          micButton.setAttribute('aria-pressed', String(state === 'recording'));
          micButton.disabled = state === 'transcribing';
        };

        const stopTracks = () => {
          recorder?.stream?.getTracks().forEach((track) => track.stop());
        };

        /* Transcription providers disagree on which recorded container/codec
           they accept (Sarvam rejects the webm/opus MediaRecorder produces).
           WAV is the one format every provider takes, so re-encode to it
           client-side rather than gambling on codec support server-side. */
        const audioBlobToWav = async (blob) => {
          const AudioCtx = window.AudioContext || window.webkitAudioContext;
          const context = new AudioCtx();
          try {
            const buffer = await context.decodeAudioData(await blob.arrayBuffer());
            const channels = buffer.numberOfChannels;
            const sampleRate = buffer.sampleRate;
            const frameCount = buffer.length;
            const interleaved = new Float32Array(frameCount * channels);
            for (let channel = 0; channel < channels; channel++) {
              const data = buffer.getChannelData(channel);
              for (let i = 0; i < frameCount; i++) interleaved[i * channels + channel] = data[i];
            }
            const bytesPerSample = 2;
            const blockAlign = channels * bytesPerSample;
            const dataSize = interleaved.length * bytesPerSample;
            const view = new DataView(new ArrayBuffer(44 + dataSize));
            const writeString = (offset, text) => {
              for (let i = 0; i < text.length; i++) view.setUint8(offset + i, text.charCodeAt(i));
            };
            writeString(0, 'RIFF');
            view.setUint32(4, 36 + dataSize, true);
            writeString(8, 'WAVE');
            writeString(12, 'fmt ');
            view.setUint32(16, 16, true);
            view.setUint16(20, 1, true);
            view.setUint16(22, channels, true);
            view.setUint32(24, sampleRate, true);
            view.setUint32(28, sampleRate * blockAlign, true);
            view.setUint16(32, blockAlign, true);
            view.setUint16(34, 16, true);
            writeString(36, 'data');
            view.setUint32(40, dataSize, true);
            let offset = 44;
            for (let i = 0; i < interleaved.length; i++, offset += 2) {
              const sample = Math.max(-1, Math.min(1, interleaved[i]));
              view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
            }
            return new Blob([view], { type: 'audio/wav' });
          } finally {
            context.close();
          }
        };

        const uploadRecording = async (recordedBlob) => {
          setMicState('transcribing');
          setMicStatus('Transcribing…');
          try {
            const blob = await audioBlobToWav(recordedBlob);
            const body = new FormData();
            body.append('session_id', sessionId);
            body.append('audio', blob, 'recording.wav');
            const response = await fetch('/api/transcribe', { method: 'POST', body });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) throw new Error(payload.detail || 'Could not transcribe that recording.');
            const text = String(payload.text || '').trim();
            if (text) {
              const prefix = input.value && !/\s$/.test(input.value) ? ' ' : '';
              input.value += prefix + text;
              input.dispatchEvent(new Event('input'));
            }
            setMicStatus('');
          } catch (error) {
            setMicStatus(error.message || 'Could not transcribe that recording.');
          } finally {
            setMicState('idle');
          }
        };

        micButton.addEventListener('click', async () => {
          if (recording) {
            recording = false;
            recorder?.stop();
            return;
          }
          try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            chunks = [];
            recorder = new MediaRecorder(stream);
            recorder.addEventListener('dataavailable', (event) => {
              if (event.data.size > 0) chunks.push(event.data);
            });
            recorder.addEventListener('stop', () => {
              stopTracks();
              const blob = new Blob(chunks, { type: recorder.mimeType || 'audio/webm' });
              if (blob.size > 0) uploadRecording(blob);
              else setMicState('idle');
            });
            recorder.start();
            recording = true;
            setMicState('recording');
            setMicStatus('Recording… tap the mic again to stop.');
          } catch (_) {
            setMicState('idle');
            setMicStatus('Microphone access was blocked. Allow it in your browser to dictate.');
          }
        });
      }
    }

    try {
      const draft = sessionStorage.getItem(draftKey);
      if (draft && !finished) input.value = draft;
    } catch (_) { /* Storage can be disabled. */ }
    autosize();

    progress();
    if (finished || turn >= MAX_TURNS) {
      finish();
    } else {
      openSocket();
    }
    scroll();
  }
})();
