export type PresetCategory = "tool" | "knowledge" | "chat";

export type PresetQuestion = {
  category: PresetCategory;
  text: string;
};

/** 输入示例：原快捷芯片条目置顶，便于在「输入示例」里选用 */
export const PRESET_QUESTIONS: PresetQuestion[] = [
  // —— 原页面快捷示例（优先展示）——
  { category: "tool", text: "我附近有哪些好吃的" },
  { category: "tool", text: "附近的充电站有哪些" },
  { category: "tool", text: "帮我导航到中关村软件园" },
  { category: "tool", text: "打开空调并播放周杰伦的晴天" },
  { category: "knowledge", text: "自动泊车怎么用" },
  { category: "tool", text: "打开飞书" },
  { category: "tool", text: "帮我搜一下今天国内油价" },
  { category: "tool", text: "帮我去总结一些昨天发生的大新闻" },
  { category: "tool", text: "最近一周的AI大事有哪些" },

  // 手册
  { category: "knowledge", text: "怎么寻找充电地点？" },
  { category: "knowledge", text: "前撞预警可以监测到哪些东西呢？" },
  { category: "knowledge", text: "智能泊车在什么状况下也许不能正常工作啊？" },
  { category: "knowledge", text: "Model 3上要咋搜索音频内容呢？" },
  { category: "knowledge", text: "若检测到外部充电设备发生故障，车辆能不能进行直流快速充电呢？" },
  { category: "knowledge", text: "车辆的最大允许总质量包含哪些部分？" },
  { category: "knowledge", text: "为什么Model 3长时间停着的时候要用充电器充电呢？" },
  { category: "knowledge", text: "前摄像头外壳里有冷凝了，怎么清洁呢？" },
  { category: "knowledge", text: "车电量耗尽的时候，在车里边打开后备箱该如何操作呢？" },
  { category: "knowledge", text: "紧急制动的情况下制动功能不正常了，怎样停车呢?" },
  { category: "knowledge", text: "用哪些方式能够关上后备箱啊?" },
  { category: "knowledge", text: "在超级充电站充电，什么情况下会被收取超时占用费呀？" },
  { category: "knowledge", text: "电池图标变成黄色代表着什么呢？" },

  // 控制指令
  { category: "tool", text: "我坐副驾，喜欢22度" },
  { category: "tool", text: "把空调打开" },
  { category: "tool", text: "导航到中关村软件园，副驾空调22度，播放周杰伦的晴天" },
  { category: "tool", text: "从当前位置导航到五道口地铁站" },
  { category: "tool", text: "播放周杰伦的晴天" },
  { category: "tool", text: "我现在播放的音乐是什么" },
  { category: "tool", text: "请给我播放下一首歌" },
  { category: "tool", text: "我现在的播放的音量多少" },
  { category: "tool", text: "我希望减少音量" },
  { category: "tool", text: "帮我打开空调" },
  { category: "tool", text: "帮我把前排空调温度调到22度" },
  { category: "tool", text: "打开后备箱" },
  { category: "tool", text: "结束导航" },

  { category: "tool", text: "附近有没有靠谱的停车场" },
  { category: "tool", text: "周边有什么好喝的咖啡" },

  // 闲聊：口语陪伴；后两句是接上一轮电影的追问示例
  { category: "chat", text: "前面又大塞车了，心情有点烦躁,有什么故事能让我心情好一点" },
  { category: "chat", text: "今天开了一天的会，脑子很乱，随便陪我聊两句放松一下吧" },
  { category: "chat", text: "周末我想开车去周边转转，如果是你的话，你会推荐去哪儿" },
  { category: "chat", text: "夜里开车感觉好孤独啊" },
  { category: "chat", text: "今天工作不顺心，想吐槽一下" },
  { category: "chat", text: "我最近比较无聊想看电影，最近有什么比较好看的电影吗" },
  { category: "chat", text: "你说说这个电影好看在哪里" },
];

export const PRESET_CATEGORY_LABEL: Record<PresetCategory, string> = {
  knowledge: "手册",
  tool: "控车",
  chat: "闲聊",
};
