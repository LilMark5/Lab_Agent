import request from '@/utils/request'

export function getEquipmentPageList(params) {
  return request({ url: '/api/equipment/list', method: 'get', params })
}

export function createEquipmentApi(data) {
  return request({ url: '/api/equipment', method: 'post', data })
}

export function updateEquipmentApi(equipmentId, data) {
  return request({ url: `/api/equipment/${equipmentId}`, method: 'put', data })
}

export function deleteEquipmentApi(equipmentId) {
  return request({ url: `/api/equipment/${equipmentId}`, method: 'delete' })
}
