import request from '@/utils/request'

export function createReservationApi(data) {
  return request({ url: '/api/reservation', method: 'post', data })
}

export function getReservationPageList(params) {
  return request({ url: '/api/reservation/list', method: 'get', params })
}

export function cancelReservationApi(id) {
  return request({ url: `/api/reservation/${id}/cancel`, method: 'put' })
}

export function auditReservationApi(id, status) {
  return request({ url: `/api/reservation/${id}/audit`, method: 'put', data: { status } })
}
