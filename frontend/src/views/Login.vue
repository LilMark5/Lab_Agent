<template>
  <div class="login-container">
    <div class="login-box">
      <h1>智能实验室预约系统</h1>
      <el-form
        ref="formRef"
        :model="form"
        :rules="rules"
        label-width="0px"
        @keyup.enter="login"
      >
        <el-form-item prop="username">
          <el-input
            v-model="form.username"
            size="large"
            placeholder="请输入账号"
            :prefix-icon="User"
          />
        </el-form-item>
        <el-form-item prop="password">
          <el-input
            v-model="form.password"
            type="password"
            size="large"
            placeholder="请输入密码"
            :prefix-icon="Lock"
            show-password
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          style="width: 100%"
          :loading="loading"
          @click="login"
        >
          登 录
        </el-button>
        <div class="register-link">
          还没有账号？<router-link to="/register">立即注册</router-link>
        </div>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { User, Lock } from '@element-plus/icons-vue'
import { useRouter, useRoute } from 'vue-router'

import { loginApi } from '@/api/auth'
import { saveLoginData } from '@/utils/auth'
import { useUser } from '@/utils/user'

const router = useRouter()
const route = useRoute()
const { updateUser } = useUser()

const formRef = ref()
const loading = ref(false)
const form = reactive({ username: '', password: '' })
const rules = {
  username: [{ required: true, message: '请输入账号', trigger: 'blur' }],
  password: [{ required: true, message: '请输入密码', trigger: 'blur' }]
}

const login = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const res = await loginApi(form)
    if (res.code === 200) {
      saveLoginData(res.data)
      updateUser(res.data.user)
      ElMessage.success('登录成功')
      const redirect = route.query.redirect || '/manager/home'
      await router.push(redirect)
    }
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-container {
  height: 100vh;
  display: flex;
  justify-content: center;
  align-items: center;
  background: linear-gradient(135deg, #e0f0ff 0%, #f5f7fa 100%);
}
.login-box {
  width: 400px;
  padding: 36px 32px;
  border-radius: 10px;
  background: white;
  box-shadow: 0 10px 24px rgba(0, 0, 0, 0.08);
  text-align: center;
}
.login-box h1 {
  font-size: 22px;
  margin-bottom: 24px;
}
.register-link {
  margin-top: 18px;
  font-size: 14px;
  color: #666;
}
.register-link a {
  color: var(--el-color-primary);
}
</style>
