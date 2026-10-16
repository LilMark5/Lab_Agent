<template>
  <el-card>
    <template #header>
      <div style="font-weight: bold">系统首页</div>
    </template>
    <el-alert
      type="success"
      :closable="false"
      show-icon
      title="欢迎使用智能实验室预约系统"
      description="这个项目把 FastAPI、Vue3、SQLAlchemy、RAG、Tool Calling、LangGraph、SSE 串联成一个完整的 AI Agent 应用。"
    />
    <div style="margin-top: 20px; display: flex; gap: 16px; flex-wrap: wrap">
      <el-card v-for="item in cards" :key="item.title" style="width: 280px">
        <div style="font-weight: bold">{{ item.title }}</div>
        <div style="color: #666; margin-top: 8px; line-height: 1.6">{{ item.desc }}</div>
      </el-card>
    </div>
  </el-card>
</template>

<script setup>
const cards = [
  {
    title: '传统业务闭环',
    desc: '用户注册登录、实验室与设备管理、预约提交与审核，先做一个完整 CRUD 系统。'
  },
  {
    title: 'RAG 知识库',
    desc: '把实验室规则、开放时间、安全规范存入 ChromaDB，让助手不编造资料。'
  },
  {
    title: 'Tool Calling',
    desc: '让模型自己决定是否调用工具，查询真实数据库中的实验室和设备。'
  },
  {
    title: 'LangGraph Agent',
    desc: '用状态图把思考、工具调用、预约确认组织成可解释的工作流。'
  },
  {
    title: 'SSE 流式输出',
    desc: '前端能实时看到“正在思考 / 查询实验室 / 提交预约”的过程。'
  }
]
</script>
