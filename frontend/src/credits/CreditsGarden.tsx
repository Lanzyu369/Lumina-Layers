import { useEffect, useId, useRef, useState } from 'react';
import Switch from '../components/ui/Switch';
import { useI18n } from '../i18n/context';
import { createCreditsGarden } from './garden-engine.js';
import type { CreditsGardenController } from './garden-engine.js';
import type { CreditsCatalog } from './types';
import './credits-garden.css';

export default function CreditsGarden({ catalog }: { catalog: CreditsCatalog }) {
  const rootRef = useRef<HTMLDivElement>(null);
  const gardenRef = useRef<CreditsGardenController | null>(null);
  const [effects, setEffects] = useState(false);
  const [motion, setMotion] = useState(() => !(window.matchMedia?.('(prefers-reduced-motion: reduce)').matches ?? false));
  const resultsId = useId();
  const { t } = useI18n();

  useEffect(() => {
    if (!rootRef.current) return;
    const garden = createCreditsGarden(rootRef.current, catalog, {
      noResults: t('credits_search_no_results'),
      found: t('credits_found'),
      source: t('credits_source'),
    });
    gardenRef.current = garden;
    return () => { gardenRef.current = null; garden.dispose(); };
  }, [catalog, t]);

  useEffect(() => {
    gardenRef.current?.setEffects(effects);
    gardenRef.current?.setMotion(motion);
  }, [catalog, effects, motion, t]);

  return (
    <div ref={rootRef} className="credits-garden">
      <div className="ambient" data-credits="ambient" aria-hidden="true" />
      <canvas className="scene" data-credits="scene" aria-label={t('credits_canvas_label')} />
      <div className="switches" data-credits="switches">
        <Switch checked={effects} onChange={setEffects} ariaLabel={t('credits_sponsor_effects')}
          checkedLabel={t('credits_sponsor_effects')} uncheckedLabel={t('credits_sponsor_effects')} />
        <Switch checked={motion} onChange={setMotion} ariaLabel={t('credits_motion')}
          checkedLabel={t('credits_motion')} uncheckedLabel={t('credits_motion')} />
      </div>
      <div className="search" data-credits="search">
        <form className="pill" data-credits="pill" role="search" autoComplete="off">
          <svg className="ic" viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="10.5" cy="10.5" r="6.5" /><path d="M15.5 15.5 20 20" />
          </svg>
          <input data-credits="q" type="search" placeholder={t('credits_search_placeholder')}
            spellCheck="false" maxLength={256} aria-label={t('credits_search_placeholder')}
            role="combobox" aria-autocomplete="list" aria-controls={resultsId} aria-expanded="false" />
          <button className="clear" data-credits="clear" type="button" disabled aria-label={t('credits_clear_search')}>
            <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M2 2l8 8M10 2 2 10" /></svg>
          </button>
          <kbd aria-hidden="true">/</kbd>
        </form>
        <ul className="results" data-credits="results" id={resultsId} role="listbox"
          aria-label={t('credits_search_results')} hidden />
        <div className="sr-only" data-credits="status" role="status" aria-live="polite" />
      </div>
      <div className="card" data-credits="card" aria-hidden="true">
        <canvas data-credits="cardAv" width={88} height={88} />
        <div><div className="nm" data-credits="cardName" /><div className="mt" data-credits="cardMeta" /></div>
      </div>
    </div>
  );
}
