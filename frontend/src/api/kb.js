import request from '@/utils/request'

export function uploadDocumentApi(file, onUploadProgress) {
  const formData = new FormData()
  formData.append('file', file)
  return request({
    url: '/api/kb/documents',
    method: 'post',
    data: formData,
    timeout: 180000,
    onUploadProgress
  })
}

export function listDocumentsApi() {
  return request({
    url: '/api/kb/documents',
    method: 'get'
  })
}

export function deleteDocumentApi(documentId) {
  return request({
    url: `/api/kb/documents/${documentId}`,
    method: 'delete'
  })
}

export function searchDocumentApi(documentId, query) {
  return request({
    url: `/api/kb/documents/${documentId}/search`,
    method: 'get',
    params: { query },
    timeout: 90000
  })
}
