import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { useEffect, useRef, useState } from 'react'
import type { TripTrack } from '../api'
import { useI18n } from '../i18n'

const TEAL = '#0f766e'

/** Bản đồ OpenStreetMap (Leaflet). Vẽ bằng divIcon tự dựng (không phụ thuộc ảnh marker); vẫn vẽ được tuyến/xe nếu tile lỗi. */
export function RouteMap({ trip, late }: { trip: TripTrack; late?: boolean }) {
  const { t } = useI18n()
  const el = useRef<HTMLDivElement>(null)
  const map = useRef<L.Map | null>(null)
  const layer = useRef<L.LayerGroup | null>(null)
  const fitted = useRef<string>('')
  const [tilesFailed, setTilesFailed] = useState(false)

  useEffect(() => {
    if (!el.current || map.current) return
    const m = L.map(el.current, { zoomControl: true, attributionControl: true }).setView([10.88, 106.77], 12)
    const tiles = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      maxZoom: 18, attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    })
    let errors = 0
    tiles.on('tileerror', () => { if (++errors > 3) setTilesFailed(true) })
    tiles.addTo(m)
    layer.current = L.layerGroup().addTo(m)
    map.current = m
    return () => { m.remove(); map.current = null }
  }, [])

  useEffect(() => {
    const m = map.current, g = layer.current
    if (!m || !g) return
    g.clearLayers()
    const route = trip.route.map((p) => [p.lat, p.lng] as [number, number])
    L.polyline(route, trip.route_source === 'osrm' ? { color: '#5b7c99', weight: 5, opacity: 0.75 } : { color: '#8aa0a8', weight: 4, dashArray: '6 8' }).addTo(g)  // đường bộ thật: nét liền; mô phỏng: nét đứt
    if (trip.track?.length) L.polyline(trip.track.map((p) => [p.lat, p.lng] as [number, number]), { color: TEAL, weight: 5 }).addTo(g)
    for (const f of trip.geofences) {
      L.circle([f.lat, f.lng], { radius: f.radius_m, color: TEAL, weight: 1, fillOpacity: 0.12 }).addTo(g)
      L.marker([f.lat, f.lng], { icon: L.divIcon({ className: 'mk', html: `<span class="mk-pin">${f.code === 'AT_ICD_GATE' ? '⚑' : '▣'}</span>`, iconSize: [26, 26] }) }).addTo(g)
    }
    if (trip.position) {
      const cls = late ? 'mk-veh late' : 'mk-veh'
      L.marker([trip.position.lat, trip.position.lng], { icon: L.divIcon({ className: 'mk', html: `<span class="${cls}">🚚</span>`, iconSize: [30, 30] }), zIndexOffset: 1000 }).bindTooltip(trip.plate).addTo(g)
    }
    const key = `${trip.proposal_id}:${trip.route_source}`
    if (fitted.current !== key) { // chỉ co giãn khung nhìn khi đổi chuyến (không giật khi polling)
      m.fitBounds(L.latLngBounds(route), { padding: [30, 30] })
      fitted.current = key
    }
  }, [trip, late])

  return (
    <div className="map-wrap">
      <div ref={el} className="map" aria-label={t('tk.map')} />
      {tilesFailed && <div className="map-note">{t('tk.tiles')}</div>}
    </div>
  )
}
