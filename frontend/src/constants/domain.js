export const domain = {
  "id": "gb-0044",
  "direction": "预测与特征选择",
  "title": "槐序干燥时长试算台",
  "slug": "drying-forest",
  "algorithm": "forest",
  "entities": "DryingStudy / DryingSample / RegressionRun / ProcessMemo",
  "scenario": "物料初始湿度/厚度/温度→干燥时长估计→工艺试验备忘；解释用留出置换重要性，禁止用留出集选参",
  "visual": "工艺温标、铁锈奶油",
  "oracle": "固定seed重复；变留出标签不改变模型选择；非法特征/样本不足拒绝",
  "frontend": 18248,
  "backend": 19248,
  "db_port": 17748,
  "database": "PostgreSQL16",
  "batch": 1,
  "code": "HX",
  "source": "干燥研究",
  "record": "试制样本",
  "note": "工艺试验备忘",
  "source_table": "drying_studies",
  "record_table": "drying_samples",
  "run_table": "regression_runs",
  "note_table": "process_memos",
  "eyebrow": "PROCESS THERMOMETRY / 44",
  "headline": "给干燥时长，一个可复查的估计。",
  "subtitle": "槐序材料试制组 · 特征子集选择与留出验证",
  "fields": [
    [
      "moisture",
      "初始湿度 %",
      "number"
    ],
    [
      "thickness",
      "厚度 mm",
      "number"
    ],
    [
      "temperature",
      "设定温度 ℃",
      "number"
    ],
    [
      "airflow",
      "风量 m³/min",
      "number"
    ],
    [
      "minutes",
      "实测时长 min",
      "number"
    ]
  ],
  "params": [
    [
      "trees",
      "森林树数",
      60
    ],
    [
      "depth",
      "最大深度",
      6
    ]
  ],
  "sample": {
    "moisture": 35,
    "thickness": 4.2,
    "temperature": 75,
    "airflow": 3.1,
    "minutes": 83
  },
  "seed_count": 240,
  "ink": "oklch(30% .06 35)",
  "accent": "oklch(57% .15 38)",
  "paper": "oklch(94% .026 78)",
  "principle": "先固定留出集，特征选择与交叉验证仅在训练行完成；留出集只作最后一次评估。置换重要性是模型依赖度，不是因果贡献。",
  "default_parameters": {
    "trees": 60,
    "depth": 6
  },
  "method_label": "RandomForest回归、训练内特征子集交叉验证与留出集MAE",
  "result_headline": "先选训练特征，再核对留出误差。",
  "column_labels": {
    "reference": "样本编号",
    "actual": "实际类型",
    "predicted": "预测类型",
    "posterior": "最高类后验",
    "cluster": "分区编号",
    "kind": "微站类型",
    "temperature": "温度 ℃",
    "humidity": "湿度 %",
    "particles": "颗粒浓度",
    "from": "当前章节",
    "to": "下一章节",
    "count": "接续次数",
    "conditional_probability": "条件概率",
    "target_base_rate": "目标章节基率",
    "lift": "提升度",
    "support": "边支持度",
    "actual_minutes": "实测时长 min",
    "predicted_minutes": "预测时长 min",
    "error_minutes": "预测误差 min",
    "visitor": "匿名访客",
    "exhibit": "展品编号",
    "prediction": "预计评分",
    "method": "计算依据",
    "neighbor_count": "参与邻居数",
    "pair_no": "配对序号",
    "reference_a": "A组样本编号",
    "reference_b": "B组样本编号",
    "minutes_a": "A组实测时长 min",
    "minutes_b": "B组实测时长 min",
    "diff_minutes": "配对时长差 min",
    "moisture_gap": "湿度差 %",
    "thickness_gap": "厚度差 mm",
    "normalized_cost": "容差折算差",
    "group": "组别",
    "candidate_count": "容差内候选数",
    "reason": "未配对原因"
  },
  "pair_table": "paired_comparisons",
  "paired": {
    "entity": "PairedComparison",
    "scenario": "两种干燥工艺接到的来料不同，不能直接比较平均时长；在同一受理截点冻结两组试件与湿度/厚度容差，按容差配对后估计配对时长差。",
    "method_label": "容差内一对一配对、最多配对优先、折算总差最小、配对差值t区间",
    "headline": "先配成对，再谈时长差。",
    "principle": "选对只看初始湿度与厚度，实测时长不参与；每件试件最多配对一次，先让合格配对最多，再让容差折算总差最小，同分按样本编号定序。未配成的试件逐条列出原因。",
    "queue": "pairing:queue",
    "confidence": 0.95,
    "min_pairs": 2,
    "limits": {
      "tolerance_humidity": 100,
      "tolerance_thickness": 1000,
      "group_records": 1000,
      "candidate_pairs": 60000
    }
  }
};
