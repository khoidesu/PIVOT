import maplibregl from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import { useEffect, useRef, useState } from 'react'
import type { TripTrack } from '../api'
import { useI18n } from '../i18n'
import { iconSvg } from './Icon'

const STYLE_URL = 'https://tiles.openfreemap.org/styles/liberty' // bản đồ vector miễn phí, không cần khoá, có sẵn toà nhà 3D
const BLANK: maplibregl.StyleSpecification = { version: 8, sources: {}, layers: [{ id: 'bg', type: 'background', paint: { 'background-color': '#e8eef0' } }] }
const TEAL = '#0f766e'
const ROAD = '#5b7c99'
const JAM = ['match', ['get', 'level'], 'low', '#2e9e5b', 'moderate', '#e0a100', 'heavy', '#d64545', 'severe', '#7a1212', 'rgba(0,0,0,0)'] as maplibregl.ExpressionSpecification // mức kẹt xe thật
type LngLat = [number, number]
type Geom = { type: 'LineString'; coordinates: LngLat[] } | { type: 'Polygon'; coordinates: LngLat[][] }
type Feat = { type: 'Feature'; properties: Record<string, string>; geometry: Geom }
type Fc = { type: 'FeatureCollection'; features: Feat[] }

const fc = (features: Feat[]): Fc => ({ type: 'FeatureCollection', features })
const line = (pts: LngLat[]): Feat => ({ type: 'Feature', properties: {}, geometry: { type: 'LineString', coordinates: pts } })

/** Vòng tròn bán kính `r` mét quanh (lng,lat) thành đa giác (MapLibre vẽ circle theo pixel nên tự dựng theo mét). */
function ring(lng: number, lat: number, r: number, n = 48): Feat {
  const dLat = r / 111320, dLng = r / (111320 * Math.cos((lat * Math.PI) / 180))
  const pts: LngLat[] = Array.from({ length: n + 1 }, (_, i) => { const a = (2 * Math.PI * i) / n; return [lng + dLng * Math.cos(a), lat + dLat * Math.sin(a)] })
  return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [pts] } }
}

function bearing(a: LngLat, b: LngLat): number {
  const toR = (d: number) => (d * Math.PI) / 180
  const y = Math.sin(toR(b[0] - a[0])) * Math.cos(toR(b[1]))
  const x = Math.cos(toR(a[1])) * Math.sin(toR(b[1])) - Math.sin(toR(a[1])) * Math.cos(toR(b[1])) * Math.cos(toR(b[0] - a[0]))
  return (Math.atan2(y, x) * 180) / Math.PI
}

const mk = (cls: string, html: string, title?: string) => {
  const d = document.createElement('div')
  d.className = cls; d.innerHTML = html
  if (title) d.title = title
  return d
}

/** Bản đồ 3D (MapLibre GL + OpenFreeMap: toà nhà 3D, nghiêng/xoay được). Vẫn vẽ được tuyến/xe khi không tải được nền. */
export function RouteMap({ trip, late }: { trip: TripTrack; late?: boolean }) {
  const { t } = useI18n()
  const box = useRef<HTMLDivElement>(null)
  const map = useRef<maplibregl.Map | null>(null)
  const markers = useRef<maplibregl.Marker[]>([])
  const fitted = useRef('')
  const [ready, setReady] = useState(false)
  const [baseFailed, setBaseFailed] = useState(false)
  const [is3d, setIs3d] = useState(true)
  const [follow, setFollow] = useState(false)

  useEffect(() => {
    let cancelled = false
    void (async () => {
      let style: maplibregl.StyleSpecification = BLANK
      try { const r = await fetch(STYLE_URL); if (!r.ok) throw new Error(String(r.status)); style = (await r.json()) as maplibregl.StyleSpecification }
      catch { setBaseFailed(true) } // không tải được nền → vẫn vẽ tuyến trên nền trơn
      if (cancelled || !box.current) return
      const m = new maplibregl.Map({ container: box.current, style, center: [106.77, 10.88], zoom: 11, pitch: 60, bearing: -20, maxPitch: 80, attributionControl: { compact: true } })
      m.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
      let errors = 0
      m.on('error', () => { if (++errors > 5) setBaseFailed(true) })
      m.on('load', () => {
        const layers = m.getStyle().layers ?? []
        if (!layers.some((l) => l.type === 'fill-extrusion') && m.getSource('openmaptiles')) { // nền không có sẵn toà nhà 3D → tự thêm
          m.addLayer({ id: 'bld3d', type: 'fill-extrusion', source: 'openmaptiles', 'source-layer': 'building', minzoom: 14,
            paint: { 'fill-extrusion-color': '#cfd8dc', 'fill-extrusion-height': ['coalesce', ['get', 'render_height'], 8], 'fill-extrusion-opacity': 0.85 } })
        }
        for (const id of ['route', 'traffic', 'track', 'fences']) m.addSource(id, { type: 'geojson', data: fc([]) })
        m.addLayer({ id: 'fences-fill', type: 'fill', source: 'fences', paint: { 'fill-color': TEAL, 'fill-opacity': 0.14 } })
        m.addLayer({ id: 'fences-line', type: 'line', source: 'fences', paint: { 'line-color': TEAL, 'line-width': 1.5 } })
        m.addLayer({ id: 'route-casing', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': '#ffffff', 'line-width': 9 } })
        m.addLayer({ id: 'route', type: 'line', source: 'route', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': ROAD, 'line-width': 5 } })
        m.addLayer({ id: 'traffic', type: 'line', source: 'traffic', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': JAM, 'line-width': 5, 'line-opacity': 0.9 } })
        m.addLayer({ id: 'track', type: 'line', source: 'track', layout: { 'line-cap': 'round', 'line-join': 'round' }, paint: { 'line-color': TEAL, 'line-width': 5 } })
        setReady(true)
      })
      map.current = m
    })()
    return () => { cancelled = true; markers.current.forEach((k) => k.remove()); markers.current = []; map.current?.remove(); map.current = null; setReady(false) }
  }, [])

  useEffect(() => { // dữ liệu tuyến / vệt / geofence / marker
    const m = map.current
    if (!m || !ready) return
    const route = trip.route.map((p) => [p.lng, p.lat] as LngLat)
    const src = (id: string) => m.getSource(id) as maplibregl.GeoJSONSource
    src('route').setData(fc([line(route)]))
    const jam = trip.eta_signals?.traffic?.segments ?? [] // lớp kẹt xe thật (Mapbox) — chỉ có khi cấu hình khoá
    src('traffic').setData(fc(jam.map((g) => ({ type: 'Feature', properties: { level: g.level }, geometry: { type: 'LineString', coordinates: g.points.map(([la, ln]) => [ln, la] as LngLat) } }))))
    src('track').setData(fc(trip.track && trip.track.length > 1 ? [line(trip.track.map((p) => [p.lng, p.lat] as LngLat))] : []))
    src('fences').setData(fc(trip.geofences.map((f) => ring(f.lng, f.lat, f.radius_m))))
    m.setPaintProperty('route', 'line-dasharray', trip.route_source === 'osrm' ? [1, 0] : [1.2, 1.6]) // đường bộ thật: nét liền; mô phỏng: nét đứt
    markers.current.forEach((k) => k.remove())
    markers.current = trip.geofences.map((f) => new maplibregl.Marker({ element: mk('mk-pin', iconSvg(f.code === 'AT_ICD_GATE' ? 'flag' : 'box', 14)) }).setLngLat([f.lng, f.lat]).addTo(m))
    if (trip.position) {
      markers.current.push(new maplibregl.Marker({ element: mk(late ? 'mk-veh late' : 'mk-veh', iconSvg('truck', 16), trip.plate) }).setLngLat([trip.position.lng, trip.position.lat]).addTo(m))
      if (follow) m.easeTo({ center: [trip.position.lng, trip.position.lat], duration: 600 })
    }
    const key = `${trip.proposal_id}:${trip.route_source}`
    if (fitted.current !== key && route.length > 1) { // chỉ co khung nhìn khi đổi chuyến/tuyến (không giật khi polling)
      const b = route.reduce((acc, p) => acc.extend(p), new maplibregl.LngLatBounds(route[0], route[0]))
      m.fitBounds(b, { padding: 60, pitch: is3d ? 60 : 0, bearing: is3d ? bearing(route[0], route[route.length - 1]) : 0, duration: 900 })
      fitted.current = key
    }
  }, [trip, late, ready, follow]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { map.current?.easeTo({ pitch: is3d ? 60 : 0, bearing: is3d ? map.current.getBearing() : 0, duration: 600 }) }, [is3d])

  return (
    <div className="map-wrap">
      <div ref={box} className="map" aria-label={t('tk.map')} />
      <div className="map-tools">
        <button className="btn sm" onClick={() => setIs3d((v) => !v)} aria-pressed={is3d}>{t(is3d ? 'tk.2d' : 'tk.3d')}</button>
        <button className={`btn sm${follow ? ' primary' : ''}`} onClick={() => setFollow((v) => !v)} aria-pressed={follow}>{t('tk.follow')}</button>
      </div>
      {baseFailed && <div className="map-note">{t('tk.tiles')}</div>}
    </div>
  )
}
