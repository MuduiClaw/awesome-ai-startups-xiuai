export function formatCurrency(amount: number): string {
  if (amount >= 1_000_000_000) {
    return `$${(amount / 1_000_000_000).toFixed(1)}B`;
  }
  if (amount >= 1_000_000) {
    return `$${(amount / 1_000_000).toFixed(0)}M`;
  }
  if (amount >= 1_000) {
    return `$${(amount / 1_000).toFixed(0)}K`;
  }
  return `$${amount}`;
}

export function formatRound(round: string): string {
  const map: Record<string, string> = {
    "pre-seed": "Pre-Seed",
    seed: "Seed",
    "series-a": "Series A",
    "series-b": "Series B",
    "series-c": "Series C",
    "series-d": "Series D",
    "series-e": "Series E",
    "series-f": "Series F",
    growth: "Growth",
    ipo: "IPO",
    unknown: "Unknown",
  };
  return map[round] || round;
}

export function cn(...classes: (string | boolean | undefined | null)[]): string {
  return classes.filter(Boolean).join(" ");
}

/** Resolve a bilingual field based on locale. Falls back to the base field. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function localized(item: any, locale: "en" | "zh", field: string = "name"): string {
  if (locale === "zh") {
    const zhValue = item[`${field}_zh`];
    if (typeof zhValue === "string" && zhValue) return zhValue;
  }
  return (item[field] as string) ?? "";
}

/** Format a pricing model string for display. */
export function formatPricingModel(model: string, locale: "en" | "zh" = "en"): string {
  const map: Record<string, Record<string, string>> = {
    free:          { en: "Free",        zh: "免费" },
    freemium:      { en: "Freemium",    zh: "免费增值" },
    "free-trial":  { en: "Free Trial",  zh: "免费试用" },
    paid:          { en: "Paid",        zh: "付费" },
    enterprise:    { en: "Enterprise",  zh: "企业版" },
    "open-source": { en: "Open Source", zh: "开源" },
    "usage-based": { en: "Usage-Based", zh: "按用量" },
  };
  return map[model]?.[locale] || model;
}

/** Format a slug-style string to title case for display. */
export function formatSlug(slug: string): string {
  return slug
    .split("-")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** Translate a country name to Chinese. Returns original if no translation. */
const countryZhMap: Record<string, string> = {
  "United States": "美国", "China": "中国", "United Kingdom": "英国",
  "Germany": "德国", "France": "法国", "Japan": "日本", "South Korea": "韩国",
  "Canada": "加拿大", "Australia": "澳大利亚", "India": "印度",
  "Israel": "以色列", "Singapore": "新加坡", "Spain": "西班牙",
  "Italy": "意大利", "Netherlands": "荷兰", "Sweden": "瑞典",
  "Switzerland": "瑞士", "Brazil": "巴西", "Ireland": "爱尔兰",
  "Finland": "芬兰", "Norway": "挪威", "Denmark": "丹麦",
  "Austria": "奥地利", "Belgium": "比利时", "Poland": "波兰",
  "Portugal": "葡萄牙", "Russia": "俄罗斯", "Turkey": "土耳其",
  "Mexico": "墨西哥", "Indonesia": "印度尼西亚", "Thailand": "泰国",
  "Vietnam": "越南", "Malaysia": "马来西亚", "Philippines": "菲律宾",
  "Taiwan": "台湾", "Hong Kong": "香港", "New Zealand": "新西兰",
  "South Africa": "南非", "Nigeria": "尼日利亚", "Egypt": "埃及",
  "UAE": "阿联酋", "United Arab Emirates": "阿联酋", "Saudi Arabia": "沙特阿拉伯",
  "Argentina": "阿根廷", "Chile": "智利", "Colombia": "哥伦比亚",
  "Czech Republic": "捷克", "Romania": "罗马尼亚", "Ukraine": "乌克兰",
  "Estonia": "爱沙尼亚", "Lithuania": "立陶宛", "Latvia": "拉脱维亚",
};

export function localizeCountry(country: string, locale: "en" | "zh"): string {
  if (locale === "zh") return countryZhMap[country] || country;
  return country;
}

/** Translate common slug-style tags to Chinese. Returns formatted slug if no match. */
const slugZhMap: Record<string, string> = {
  // target_audience
  "enterprises": "企业", "developers": "开发者", "researchers": "研究人员",
  "students": "学生", "marketers": "营销人员", "designers": "设计师",
  "writers": "作者", "educators": "教育者", "data-scientists": "数据科学家",
  "sales-teams": "销售团队", "call-centers": "呼叫中心",
  "content-creators": "内容创作者", "product-managers": "产品经理",
  "hr-professionals": "人力资源", "legal-professionals": "法律专业人士",
  "small-businesses": "中小企业", "freelancers": "自由职业者",
  "musicians": "音乐人", "podcasters": "播客", "photographers": "摄影师",
  "seo-specialists": "SEO专家",
  // use_cases
  "code-generation": "代码生成", "image-editing": "图像编辑",
  "text-generation": "文本生成", "data-analysis": "数据分析",
  "customer-support": "客户支持", "content-creation": "内容创作",
  "call-transcription": "通话转录", "call-summarization": "通话摘要",
  "call-automation": "通话自动化", "crm-integration": "CRM集成",
  "speech-to-text": "语音转文字", "text-to-speech": "文字转语音",
  "image-generation": "图像生成", "video-editing": "视频编辑",
  "translation": "翻译", "summarization": "摘要生成",
  "chatbot": "聊天机器人", "voice-assistant": "语音助手",
  "sentiment-analysis": "情感分析", "seo-optimization": "SEO优化",
  "content-optimization": "内容优化", "article-writing": "文章写作",
  "lead-generation": "线索生成", "email-marketing": "邮件营销",
  "social-media": "社交媒体", "project-management": "项目管理",
  "document-processing": "文档处理", "workflow-automation": "工作流自动化",
  "speech-recognition": "语音识别", "transcription": "转录",
  "voice-synthesis": "语音合成",
  // product_type
  "app": "应用", "llm": "大语言模型", "dev-tool": "开发工具",
  "hardware": "硬件", "dataset": "数据集", "framework": "框架",
  "api-service": "API服务", "other": "其他",
};

export function formatSlugLocalized(slug: string, locale: "en" | "zh"): string {
  if (locale === "zh") return slugZhMap[slug] || formatSlug(slug);
  return formatSlug(slug);
}

/** Format a number with K/M/B suffix. */
export function formatNumber(num: number): string {
  if (num >= 1_000_000_000) return `${(num / 1_000_000_000).toFixed(1)}B`;
  if (num >= 1_000_000) return `${(num / 1_000_000).toFixed(1)}M`;
  if (num >= 1_000) return `${(num / 1_000).toFixed(0)}K`;
  return String(num);
}
