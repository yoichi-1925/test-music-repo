import { useEffect, useMemo, useRef } from 'react'
import abcjs from 'abcjs'
import type { ScoreEvent, StaffScore as Score } from './api'
import { isActive } from './timing'

export default function StaffScore({ score, time, follow, onSeek }: {
  score: Score; time: number; follow: boolean; onSeek: (seconds: number) => void
}) {
  const container = useRef<HTMLDivElement>(null)
  const scroll = useRef<HTMLDivElement>(null)
  const seek = useRef(onSeek)
  seek.current = onSeek
  const bindings = useRef<{ event: ScoreEvent; elements: SVGElement[] }[]>([])
  const events = useMemo(() => score.bars.flatMap(bar => bar.events), [score])
  const active = events.findIndex(event => isActive(time, event))
  useEffect(() => {
    if (!container.current) return
    const [tune] = abcjs.renderAbc(container.current, score.abc, {
      add_classes: true, responsive: 'resize', staffwidth: 900, oneSvgPerLine: true,
      ariaLabel: '推定メロディの五線譜',
      clickListener: element => {
        const event = events.find(item => element.startChar === item.full_abc_start)
        if (event) seek.current(event.start)
      },
    })
    bindings.current = tune.getSelectableArray().flatMap(item => {
      const event = events.find(event => item.absEl.abcelem.startChar === event.full_abc_start)
      if (!event) return []
      const elements = item.absEl.elemset
      if (event.midi !== null && (event.confidence ?? 1) < .65) elements.forEach(element => element.classList.add('staff-uncertain'))
      return [{event, elements}]
    })
    return () => { bindings.current = []; if (container.current) container.current.replaceChildren() }
  }, [score, events])
  useEffect(() => {
    let target: SVGElement | undefined
    for (const item of bindings.current) {
      const playing = isActive(time, item.event)
      item.elements.forEach(element => element.classList.toggle('staff-active', playing))
      if (playing) target = item.elements[0]
    }
    if (follow && target && scroll.current) {
      const box = target.getBoundingClientRect(), parent = scroll.current.getBoundingClientRect()
      if (box.top < parent.top + 30 || box.bottom > parent.bottom - 30) {
        scroll.current.scrollTo({top: scroll.current.scrollTop + box.top - parent.top - 90, behavior:'auto'})
      }
    }
  }, [active, follow, score, time])
  return <div className="staff-viewport" ref={scroll}><div ref={container} className="staff-paper"/><span className="sr-only" aria-live="off">現在の音符: {active >= 0 ? `${events[active].midi ?? '休符'}` : '区間外'}</span></div>
}
