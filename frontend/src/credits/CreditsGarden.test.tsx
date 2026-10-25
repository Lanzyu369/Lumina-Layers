import { StrictMode } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import CreditsGarden from './CreditsGarden';
import type { CreditsCatalog } from './types';

const catalog: CreditsCatalog = {
  assetsBase: 'https://credits.example.test/data/', stale: false,
  records: Array.from({ length: 24 }, (_, i) => ({
    id: String(i), name: i < 10 ? '小林' : `成员${i}`,
    source: `平台${i}`, tier: i % 8, dev: i === 2, brand: false,
  })),
};

let frames: Map<number, FrameRequestCallback>;
let frameId: number;
let observed: (() => void)[];
let bounds: { left: number; top: number; width: number; height: number };
let disconnect: ReturnType<typeof vi.fn>;
let sceneAvatars: { x: number; y: number; width: number; height: number }[];
let paintedNames: WeakSet<HTMLCanvasElement>;
let nicknameTextures: WeakMap<HTMLCanvasElement, string>;
let sceneNames: { name: string; opacity: number }[];

function runFrame(time = 16) {
  const pending = [...frames.values()]; frames.clear();
  sceneAvatars = [];
  sceneNames = [];
  act(() => pending.forEach(callback => callback(time)));
}

beforeEach(() => {
  frames = new Map(); frameId = 0; observed = [];
  sceneAvatars = []; paintedNames = new WeakSet();
  nicknameTextures = new WeakMap(); sceneNames = [];
  bounds = { left: 120, top: 90, width: 900, height: 640 };
  disconnect = vi.fn();
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frames.set(++frameId, callback); return frameId;
  });
  vi.stubGlobal('cancelAnimationFrame', (id: number) => frames.delete(id));
  vi.stubGlobal('matchMedia', () => ({ matches: false }));
  vi.stubGlobal('ResizeObserver', class {
    constructor(callback: () => void) { observed.push(callback); }
    observe() {} disconnect = disconnect;
  });
  vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function (this: HTMLElement) {
    let { left, top, width, height } = bounds;
    if (this.dataset.credits === 'pill') {
      left += width / 2 - 180; top += height * .54 - 26; width = 360; height = 52;
    } else if (this.dataset.credits === 'switches') {
      left += width - 250; top += 16; width = 230; height = 40;
    }
    return { left, top, width, height, right: left + width, bottom: top + height,
      x: left, y: top, toJSON: () => ({}) };
  });
  const noop = () => {};
  const canvas2dPrototype = HTMLCanvasElement.prototype as {
    getContext(contextId: '2d'): CanvasRenderingContext2D | null;
  };
  vi.spyOn(canvas2dPrototype, 'getContext').mockImplementation(function (this: HTMLCanvasElement) {
    const context: Record<string, unknown> = {
    canvas: this,
    font: '11px sans-serif',
    globalAlpha: 1,
    measureText(text: string) { return { width: Array.from(text).length * 8 }; },
    fillText: (text: string) => {
      paintedNames.add(this);
      nicknameTextures.set(this, (nicknameTextures.get(this) ?? '') + text);
    },
    drawImage: (source: CanvasImageSource, x: number, y: number, width: number, height: number) => {
      if (this.dataset.credits === 'scene' && source instanceof HTMLCanvasElement) {
        const name = nicknameTextures.get(source);
        if (name) sceneNames.push({ name, opacity: Number(context.globalAlpha) });
        else if (!paintedNames.has(source)) sceneAvatars.push({ x: x + width / 2, y: y + height / 2, width, height });
      }
    },
    createLinearGradient: () => ({ addColorStop: noop }),
    createRadialGradient: () => ({ addColorStop: noop }),
    createConicGradient: () => ({ addColorStop: noop }),
    };
    return new Proxy(context, { get(target, key) { return Reflect.get(target, key) ?? noop; } }) as unknown as CanvasRenderingContext2D;
  });
  Object.defineProperty(window, 'devicePixelRatio', { configurable: true, value: 2 });
});

afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe('credits garden', () => {
  it('starts effects off on every visit, regardless of the prior visit', () => {
    const first = render(<CreditsGarden catalog={catalog} />);
    const button = screen.getByRole('switch', { name: /赞助特效|credits_sponsor_effects/ });
    expect(button).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(button);
    expect(button).toHaveAttribute('aria-checked', 'true');
    expect(disconnect).not.toHaveBeenCalled();
    first.unmount();
    render(<CreditsGarden catalog={catalog} />);
    expect(screen.getByRole('switch', { name: /赞助特效|credits_sponsor_effects/ })).toHaveAttribute('aria-checked', 'false');
  });

  it('initializes the motion switch from reduced-motion and toggles without recreating the garden', () => {
    vi.stubGlobal('matchMedia', () => ({ matches: true }));
    render(<CreditsGarden catalog={catalog} />);
    const motion = screen.getByRole('switch', { name: /动态效果|credits_motion/ });
    expect(motion).toHaveAttribute('aria-checked', 'false');
    fireEvent.click(motion);
    expect(motion).toHaveAttribute('aria-checked', 'true');
    expect(disconnect).not.toHaveBeenCalled();
    expect(frames.size).toBe(1);
  });

  it('excludes the empty-query clear button from dialog focus targets and enables it for a query', () => {
    render(<CreditsGarden catalog={catalog} />);
    const clear = screen.getByRole('button', { name: /清空搜索|credits_clear_search/ });
    const input = screen.getByRole('combobox');
    expect(clear).toBeDisabled();
    fireEvent.input(input, { target: { value: '小林' } });
    expect(clear).toBeEnabled();
    fireEvent.submit(screen.getByRole('search'));
    expect(clear).toBeEnabled();
    fireEvent.click(clear);
    expect(clear).toBeDisabled();
    expect(input).toHaveValue('');
  });

  it('uses the garden rectangle at native DPR and observes local resizes', () => {
    const { container } = render(<CreditsGarden catalog={catalog} />);
    runFrame();
    const canvas = container.querySelector('canvas')!;
    expect(canvas.width).toBe(1800);
    expect(canvas.height).toBe(1280);
    bounds = { ...bounds, width: 560, height: 420 };
    act(() => observed.forEach(callback => callback()));
    expect(canvas.width).toBe(1120);
    expect(canvas.height).toBe(840);
    expect(container.firstElementChild).toHaveAttribute('data-pixel-ratio', '2');
  });

  it('preserves every exact same-name platform account and supports keyboard selection', () => {
    render(<CreditsGarden catalog={catalog} />);
    fireEvent.input(screen.getByRole('combobox'), { target: { value: '小林' } });
    expect(screen.getAllByRole('option')).toHaveLength(10);
    expect(screen.getByText('平台0')).toBeInTheDocument();
    expect(screen.getByText('平台9')).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole('combobox'), { key: 'ArrowDown' });
    const selected = screen.getAllByRole('option').find(option => option.getAttribute('aria-selected') === 'true')!;
    const source = selected.querySelector('.tg')!.textContent;
    fireEvent.submit(screen.getByRole('search'));
    expect(screen.queryAllByRole('option')).toHaveLength(0);
    expect(screen.getByRole('combobox')).toHaveValue('小林');
    expect(screen.getByRole('status').textContent).toContain('小林');
    expect(source).toMatch(/^平台\d+$/);
  });

  it('keeps keyboard-selected duplicate accounts visible by scrolling only the result list', () => {
    render(<CreditsGarden catalog={catalog} />);
    const input = screen.getByRole('combobox');
    fireEvent.input(input, { target: { value: '小林' } });
    const list = screen.getByRole('listbox');
    Object.defineProperty(list, 'clientHeight', { configurable: true, value: 96 });
    screen.getAllByRole('option').forEach((option, index) => {
      Object.defineProperty(option, 'offsetTop', { configurable: true, value: index * 48 });
      Object.defineProperty(option, 'offsetHeight', { configurable: true, value: 48 });
    });
    const pageScroll = vi.spyOn(window, 'scrollTo');
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(list.scrollTop).toBe(0);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(list.scrollTop).toBe(48);
    fireEvent.keyDown(input, { key: 'ArrowDown' });
    expect(list.scrollTop).toBe(96);
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    fireEvent.keyDown(input, { key: 'ArrowUp' });
    expect(list.scrollTop).toBe(48);
    expect(pageScroll).not.toHaveBeenCalled();
  });

  it('consumes Escape while clearing search so the outer dialog stays open', () => {
    const outerEscape = vi.fn();
    render(<div onKeyDown={outerEscape}><CreditsGarden catalog={catalog} /></div>);
    const input = screen.getByRole('combobox');
    fireEvent.input(input, { target: { value: '成员' } });
    fireEvent.keyDown(input, { key: 'Escape' });
    expect(input).toHaveValue('');
    expect(outerEscape).not.toHaveBeenCalled();
    expect(input).toHaveAttribute('aria-expanded', 'false');
  });

  it('clears selection when the query is erased and cannot submit a stale result', () => {
    render(<CreditsGarden catalog={catalog} />);
    const input = screen.getByRole('combobox');
    fireEvent.input(input, { target: { value: '小林' } });
    fireEvent.submit(screen.getByRole('search'));
    expect(screen.getByRole('status').textContent).not.toBe('');
    fireEvent.input(input, { target: { value: '' } });
    fireEvent.submit(screen.getByRole('search'));
    expect(input).toHaveValue('');
    expect(screen.getByRole('status').textContent).toBe('');
    expect(input).not.toHaveAttribute('aria-activedescendant');
  });

  it('treats account names as literal text in both results and the selected announcement', () => {
    const name = '$&<b>名字</b>';
    const special = { ...catalog, records: [{ ...catalog.records[0], name }] };
    render(<CreditsGarden catalog={special} />);
    fireEvent.input(screen.getByRole('combobox'), { target: { value: name } });
    expect(screen.getByRole('option').textContent).toContain(name);
    expect(screen.getByRole('option').querySelector('b')).toBeNull();
    fireEvent.submit(screen.getByRole('search'));
    expect(screen.getByRole('status').textContent).toContain(name);
  });

  it('keeps a search-selected account when its visible bubble has already begun an ambient swap', () => {
    let seed = 20261026;
    vi.spyOn(Math, 'random').mockImplementation(() => {
      seed = (seed + 0x6d2b79f5) >>> 0;
      let n = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      n = (n + Math.imul(n ^ (n >>> 7), 61 | n)) ^ n;
      return ((n ^ (n >>> 14)) >>> 0) / 4294967296;
    });
    const common: CreditsCatalog = { ...catalog, records: Array.from({ length: 400 }, (_, i) => ({
      id: String(i), name: `成员${i}`, source: `平台${i}`, tier: 0, dev: false, brand: false,
    })) };
    const { container } = render(<CreditsGarden catalog={common} />);
    let fadingName: string | undefined;
    let previous = new Map<string, number>();
    let frame = 0;
    // Observe an actual fully visible nickname starting to fade, rather than
    // inject a swap or expose engine state solely for the test.
    for (; frame < 900 && !fadingName; frame++) {
      runFrame((frame + 1) * 17);
      if (frame > 200) fadingName = sceneNames.find(({ name, opacity }) => (previous.get(name) ?? 0) >= .999 && opacity < .99 && opacity > .5)?.name;
      previous = new Map(sceneNames.map(({ name, opacity }) => [name, opacity]));
    }
    expect(fadingName).toBeDefined();
    const selected = common.records.find(record => record.name === fadingName)!;
    const input = screen.getByRole('combobox');
    fireEvent.input(input, { target: { value: selected.name } });
    fireEvent.submit(screen.getByRole('search'));
    for (let end = frame + 120; frame < end; frame++) runFrame((frame + 1) * 17);
    expect(container.querySelector('[data-credits="card"]')).toHaveClass('on');
    expect(container.querySelector('[data-credits="cardName"]')?.textContent).toBe(selected.name);
    expect(container.querySelector('[data-credits="cardMeta"]')?.textContent).toContain(selected.source);
    expect(input).toHaveValue(selected.name);
    expect(screen.getByRole('status').textContent).toContain(selected.name);
    expect(sceneNames.find(({ name }) => name === selected.name)?.opacity).toBe(1);
  });

  it('cancels animation and input listeners on disposal, including StrictMode remounts', () => {
    const { container, unmount } = render(<StrictMode><CreditsGarden catalog={catalog} /></StrictMode>);
    expect(frames.size).toBe(1);
    const cardAvatar = container.querySelector<HTMLCanvasElement>('[data-credits="cardAv"]')!;
    expect(cardAvatar.width).toBe(88);
    expect(cardAvatar.height).toBe(88);
    const input = screen.getByRole('combobox');
    unmount();
    expect(frames.size).toBe(0);
    expect(disconnect).toHaveBeenCalledTimes(2);
    input.setAttribute('aria-expanded', 'false');
    fireEvent.input(input, { target: { value: '小林' } });
    expect(input).toHaveAttribute('aria-expanded', 'false');
    window.dispatchEvent(new KeyboardEvent('keydown', { key: '/' }));
    expect(document.activeElement).not.toBe(input);
  });

  it('pauses animation while hidden and resumes with one scheduled frame', () => {
    render(<CreditsGarden catalog={catalog} />);
    Object.defineProperty(document, 'hidden', { configurable: true, value: true });
    fireEvent(document, new Event('visibilitychange'));
    expect(frames.size).toBe(0);
    Object.defineProperty(document, 'hidden', { configurable: true, value: false });
    fireEvent(document, new Event('visibilitychange'));
    expect(frames.size).toBe(1);
  });

  it('pops at root-relative pointer coordinates and restores the bubble after the fall', () => {
    const common: CreditsCatalog = { ...catalog, records: Array.from({ length: 80 }, (_, i) => ({
      id: String(i), name: `成员${i}`, source: '社区', tier: 0, dev: false, brand: false,
    })) };
    const { container } = render(<CreditsGarden catalog={common} />);
    for (let i = 1; i <= 200; i++) runFrame(i * 17);
    const garden = container.firstElementChild!;
    const count = Number(garden.getAttribute('data-visible-count'));
    expect(count).toBeGreaterThan(35);
    const target = sceneAvatars.find(avatar => avatar.y > 120 && avatar.y < 300)!;
    expect(target).toBeDefined();
    const canvas = container.querySelector('canvas')!;
    // A plain Event preserves pointer coordinates in jsdom's PointerEvent fallback.
    const pointer = (name: string) => {
      const event = new Event(name, { bubbles: true });
      Object.assign(event, { clientX: bounds.left + target.x, clientY: bounds.top + target.y, pointerType: 'mouse' });
      fireEvent(canvas, event);
    };
    pointer('pointerdown'); pointer('pointerup'); runFrame(201 * 17);
    expect(Number(garden.getAttribute('data-visible-count'))).toBe(count - 1);
    for (let i = 202; i <= 470; i++) runFrame(i * 17);
    expect(Number(garden.getAttribute('data-visible-count'))).toBe(count);
  });
});
