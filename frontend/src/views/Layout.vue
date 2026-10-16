<template>
  <el-container style="height: 100vh">
    <el-aside width="220px" class="aside">
      <div class="logo">智能实验室预约</div>
      <el-menu
        router
        :default-active="route.path"
        background-color="#001529"
        text-color="#c0c4cc"
        active-text-color="#409eff"
      >
        <el-menu-item index="/manager/home">
          <el-icon><HomeFilled /></el-icon>
          <span>系统首页</span>
        </el-menu-item>

        <el-menu-item v-if="userInfo?.role === 'student'" index="/manager/lablist">
          <el-icon><OfficeBuilding /></el-icon>
          <span>实验室列表</span>
        </el-menu-item>

        <el-menu-item v-if="userInfo?.role === 'student'" index="/manager/my-reservation">
          <el-icon><Tickets /></el-icon>
          <span>我的预约</span>
        </el-menu-item>

        <el-menu-item v-if="userInfo?.role === 'admin'" index="/manager/lab">
          <el-icon><OfficeBuilding /></el-icon>
          <span>实验室管理</span>
        </el-menu-item>
        <el-menu-item v-if="userInfo?.role === 'admin'" index="/manager/equipment">
          <el-icon><Setting /></el-icon>
          <span>设备管理</span>
        </el-menu-item>
        <el-menu-item v-if="userInfo?.role === 'admin'" index="/manager/user">
          <el-icon><User /></el-icon>
          <span>用户管理</span>
        </el-menu-item>
        <el-menu-item v-if="userInfo?.role === 'admin'" index="/manager/audit-reservation">
          <el-icon><DocumentChecked /></el-icon>
          <span>预约审核</span>
        </el-menu-item>

        <el-menu-item index="/manager/ai-chat">
          <el-icon><ChatDotRound /></el-icon>
          <span>AI智能助手</span>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <el-container>
      <el-header class="header">
        <div class="header-title">毕业设计 · AI Agent 综合实践</div>
        <el-dropdown @command="handleCommand">
          <div class="user-info">
            <el-avatar :size="30" :src="userInfo?.avatar || ''">
              {{ userInfo?.name?.slice(0, 1) }}
            </el-avatar>
            <span>{{ userInfo?.name }}</span>
            <el-icon><ArrowDown /></el-icon>
          </div>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="profile">个人信息</el-dropdown-item>
              <el-dropdown-item command="password">修改密码</el-dropdown-item>
              <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { useRoute, useRouter } from 'vue-router'

import { useUser } from '@/utils/user'

const route = useRoute()
const router = useRouter()
const { userInfo, clearUser } = useUser()

const handleCommand = (command) => {
  if (command === 'profile') router.push('/manager/profile')
  else if (command === 'password') router.push('/manager/password')
  else if (command === 'logout') {
    clearUser()
    router.push('/login')
  }
}
</script>

<style scoped>
.aside {
  background: #001529;
}
.logo {
  height: 60px;
  line-height: 60px;
  color: white;
  text-align: center;
  font-weight: bold;
  letter-spacing: 1px;
}
.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  border-bottom: 1px solid #eee;
}
.header-title {
  font-weight: 600;
}
.user-info {
  display: flex;
  align-items: center;
  gap: 8px;
  cursor: pointer;
}
.main {
  background: #f5f7fa;
}
</style>
