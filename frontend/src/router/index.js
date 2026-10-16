import { createRouter, createWebHistory } from 'vue-router'

import { getToken, getUser } from '@/utils/auth'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true }
  },
  {
    path: '/register',
    name: 'Register',
    component: () => import('@/views/Register.vue'),
    meta: { public: true }
  },
  {
    path: '/manager',
    component: () => import('@/views/Layout.vue'),
    redirect: '/manager/home',
    children: [
      { path: 'home', name: 'Home', component: () => import('@/views/Home.vue') },
      { path: 'profile', name: 'Profile', component: () => import('@/views/Profile.vue') },
      { path: 'password', name: 'Password', component: () => import('@/views/Password.vue') },
      {
        path: 'user',
        name: 'User',
        component: () => import('@/views/User.vue'),
        meta: { admin: true }
      },
      { path: 'lab', name: 'Lab', component: () => import('@/views/Lab.vue') },
      { path: 'equipment', name: 'Equipment', component: () => import('@/views/Equ.vue') },
      { path: 'lablist', name: 'LabList', component: () => import('@/views/LabList.vue') },
      {
        path: 'lab-equipment',
        name: 'LabEquipment',
        component: () => import('@/views/LabEquipment.vue')
      },
      {
        path: 'my-reservation',
        name: 'MyReservation',
        component: () => import('@/views/MyReservation.vue')
      },
      {
        path: 'audit-reservation',
        name: 'AuditReservation',
        component: () => import('@/views/AuditReservation.vue'),
        meta: { admin: true }
      },
      { path: 'ai-chat', name: 'AIChat', component: () => import('@/views/AIChat.vue') },
      {
        path: 'kb-manage',
        name: 'KbManage',
        component: () => import('@/views/KbManage.vue'),
        meta: { admin: true }
      }
    ]
  },
  { path: '/', redirect: '/manager/home' },
  { path: '/:pathMatch(.*)*', redirect: '/manager/home' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 全局路由守卫：没有登录就回登录页；已登录访问登录页则回首页。
router.beforeEach((to) => {
  const token = getToken()
  if (!to.meta.public && !token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && token) {
    return { path: '/manager/home' }
  }
  // 管理员专属页面：非 admin 角色重定向回首页。
  if (to.meta.admin && getUser()?.role !== 'admin') {
    return { path: '/manager/home' }
  }
  return true
})

export default router
