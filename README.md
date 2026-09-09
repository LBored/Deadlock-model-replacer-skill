# Deadlock-model-replacer

一个用于制作和修复游戏角色模型替换 Mod 的 Codex Skill。它指导 Codex 完成资源发现、基线锁定、骨架与权重适配、材质、实时布料、编译、封包和分层验收，并附带两个只读审计脚本。

## 安装

将整个 `game-model-replacer` 目录复制到 Codex 的技能目录。已设置 `CODEX_HOME` 时放入 `$CODEX_HOME/skills/`；否则使用当前 Codex 环境配置的个人技能目录。保留目录结构，不要只复制 `SKILL.md`。

新会话中可直接调用：

```text
使用 $game-model-replacer，将我提供的模型制作成目标游戏角色的模型替换 Mod。
请先核对游戏版本、目标资源路径、工具兼容性和已有基线，再完成绑定、材质、物理、编译、打包与验收。
```

## 目录结构

```text
game-model-replacer/
├─ SKILL.md                         Codex 入口与工作流路由
├─ README.md                        面向使用者的安装与范围说明
├─ LICENSE                          MIT 许可证，仅覆盖本技能包
├─ agents/openai.yaml               Codex UI 元数据
├─ assets/project-config.example.json
├─ references/
│  ├─ discovery-and-baselines.md    资源发现和版本基线
│  ├─ mesh-and-materials.md         模型、绑定、材质和导出
│  ├─ physics-and-debugging.md      物理与症状诊断
│  ├─ release-validation.md         封包、范围和交付
│  ├─ source2.md                    通用 Source 2 专项规则
│  ├─ ui-and-voice.md               可选 UI 与语音扩展
│  └─ cases/
│     └─ deadlock-mutsumi-graves.md 独立案例，不提供默认参数
└─ scripts/
   ├─ asset_audit.py                目录/VPK 哈希与差异范围检查
   └─ blender_audit.py              Blender 场景只读审计
```

## 通用规则与案例的边界

核心参考只描述可以迁移到其他项目的判断方法和验证不变量。Deadlock 若叶睦替换格瑞墓项目中的角色路径、工具版本、资源数量、材质参数、物理节点、UI 尺寸、语音参数和故障结果集中在 `references/cases/deadlock-mutsumi-graves.md`。

案例用于解释一种问题如何被发现和验证，不表示：

- 其他 Deadlock 构建仍使用相同路径、格式或参数；
- 其他英雄具有相同骨骼、关节、布料或 UI 资源；
- 其他游戏可以使用 Source 2 工具链；
- 案例素材、游戏资源或第三方模型随本技能获得再分发许可。

使用案例前应从当前游戏和工具重新探测事实。用户的项目路径、存储政策、授权范围和验收选择不会从案例继承。

## 辅助脚本

`asset_audit.py` 使用 Python 3.10+ 标准库，可为普通目录或 Valve VPK v1/v2 生成 SHA-256 清单。VPK 模式检查逐资源 CRC；比较模式可限制允许新增、改变和删除的路径。它不解析游戏依赖，也不替代包级 MD5 或引擎校验器。

清单默认只记录输入文件或目录名，不写绝对路径。确需本地路径辅助诊断时可给 `snapshot` 增加 `--include-source-path`；含绝对路径的报告不应直接公开。

```text
python scripts/asset_audit.py snapshot --input accepted.vpk --output accepted.json
python scripts/asset_audit.py snapshot --input candidate.vpk --output candidate.json
python scripts/asset_audit.py compare --baseline accepted.json --candidate candidate.json --allow-change "models/target.vmdl_c" --output delta.json
```

`blender_audit.py` 必须由 Blender 运行，只读报告骨架、网格、权重、材质和图片引用，不修改或保存输入文件。

```text
blender --background --disable-autoexec input.blend --python scripts/blender_audit.py -- --output audit.json --max-influences 4
```

Blender 报告同样默认只写输入和图片的文件名；只有本地诊断需要完整路径时才增加 `--include-paths`。

具体限制和退出码见技能内相关参考。

## 分发范围

本仓库只应包含技能文档、配置示例和原创审计脚本。不要加入游戏二进制、解包资源、第三方人物模型、纹理、用户截图、声音模型、SDK、编译器或私人路径。

`LICENSE` 的 MIT 条款只覆盖本技能包内由贡献者创作的文本、配置示例和脚本，不授予任何游戏、角色、第三方模型、图片、声音或商标权利。使用者需自行确认其素材、工具与发布方式的许可。

## 验证

技能格式可用 Codex 的 `skill-creator/scripts/quick_validate.py` 检查。两个脚本还应以合成异常样例和至少一个实际候选包执行功能测试。验证报告不能替代游戏内动画、布料和死亡/复活验收。

## License

MIT。参见 [LICENSE](LICENSE)。第三方内容不在许可范围内。
