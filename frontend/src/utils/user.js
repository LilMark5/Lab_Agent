// 全局共享的当前用户状态。
// 用 ref 是为了让修改用户信息后，Layout 等所有用到它的组件都能响应式刷新。

import { ref } from 'vue'

import { getUser, logout as clearAuth, setUser } from './auth'

const userInfo = ref(getUser())

export function useUser() {
  function updateUser(user) {
    userInfo.value = user
    setUser(user)
  }

  function clearUser() {
    userInfo.value = null
    clearAuth()
  }

  return { userInfo, updateUser, clearUser }
}
