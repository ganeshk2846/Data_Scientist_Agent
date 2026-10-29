import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * Dictation through the Web Speech API.
 *
 * The API is non-standard and unevenly shipped, so support is *detected*, never
 * assumed — `supported` is false in Firefox and in every browser that has the
 * constructor but no recognition service behind it, and the mic button is not
 * rendered at all in that case. There is no fallback and no polyfill: a button
 * that cannot work should not be on the screen.
 *
 * Interim results stream into `transcript` so the field fills as the reader
 * speaks; `final` flips once the engine commits, which is the cue to stop.
 */

/* The vendor interface, declared narrowly — only what is actually read here. */
interface SpeechAlternative {
  transcript: string;
}
interface SpeechResult {
  readonly length: number;
  isFinal: boolean;
  [index: number]: SpeechAlternative;
}
interface SpeechResultList {
  readonly length: number;
  [index: number]: SpeechResult;
}
interface SpeechEvent {
  resultIndex: number;
  results: SpeechResultList;
}
interface SpeechErrorEvent {
  error: string;
}
interface Recognition {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult: ((event: SpeechEvent) => void) | null;
  onerror: ((event: SpeechErrorEvent) => void) | null;
  onend: (() => void) | null;
}
type RecognitionConstructor = new () => Recognition;

function constructor(): RecognitionConstructor | null {
  if (typeof window === 'undefined') return null;
  const candidate = window as unknown as {
    SpeechRecognition?: RecognitionConstructor;
    webkitSpeechRecognition?: RecognitionConstructor;
  };
  return candidate.SpeechRecognition ?? candidate.webkitSpeechRecognition ?? null;
}

export interface SpeechController {
  /** False when there is no recognition engine. The caller renders nothing. */
  supported: boolean;
  listening: boolean;
  /** What has been heard so far, interim results included. */
  transcript: string;
  /** Set when the engine refused or failed, for a toast. */
  error: string | null;
  start: () => void;
  stop: () => void;
}

const MESSAGE: Record<string, string> = {
  'not-allowed': 'Microphone access was declined.',
  'service-not-allowed': 'This browser would not start its speech service.',
  'no-speech': 'Nothing was heard.',
  'audio-capture': 'No microphone was found.',
  network: 'The speech service could not be reached.',
};

export function useSpeech(onFinal?: (text: string) => void): SpeechController {
  const [supported] = useState(() => constructor() !== null);
  const [listening, setListening] = useState(false);
  const [transcript, setTranscript] = useState('');
  const [error, setError] = useState<string | null>(null);
  const recognition = useRef<Recognition | null>(null);
  const finalRef = useRef(onFinal);
  finalRef.current = onFinal;

  const stop = useCallback(() => {
    recognition.current?.stop();
    setListening(false);
  }, []);

  const start = useCallback(() => {
    const Ctor = constructor();
    if (!Ctor) return;
    // Abort any previous session, so a double-tap cannot stack two engines.
    recognition.current?.abort();

    const instance = new Ctor();
    instance.lang = 'en-US';
    instance.continuous = false;
    instance.interimResults = true;
    instance.maxAlternatives = 1;

    instance.onresult = (event) => {
      let heard = '';
      for (let index = 0; index < event.results.length; index += 1) {
        const result = event.results[index];
        heard += result?.[0]?.transcript ?? '';
      }
      const trimmed = heard.trim();
      setTranscript(trimmed);
      const last = event.results[event.results.length - 1];
      if (last?.isFinal && trimmed) finalRef.current?.(trimmed);
    };
    instance.onerror = (event) => {
      setError(MESSAGE[event.error] ?? 'Dictation stopped unexpectedly.');
      setListening(false);
    };
    instance.onend = () => setListening(false);

    recognition.current = instance;
    setTranscript('');
    setError(null);
    try {
      instance.start();
      setListening(true);
    } catch {
      // `start()` throws if the engine is already running; nothing to recover.
      setListening(false);
    }
  }, []);

  useEffect(() => () => recognition.current?.abort(), []);

  return { supported, listening, transcript, error, start, stop };
}
