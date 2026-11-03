# ADK · Agente IA MultiTool + Seguridad (Model Armor)

Proyecto de Google ADK. Cada agente vive en su propia carpeta dentro de `adk_apps/`:

```
adk_apps/
└── adk_agenteia_tramibot_seguridad_model_armor/     # TramiBot: trámites del Municipio de Girardota (Gemini 3.5 Flash + RAG + Model Armor)
```

`adk web adk_apps` lista cada subcarpeta como un agente. Para sumar uno nuevo, crea `adk_apps/<nombre_snake_case>/` con `__init__.py` (`from . import agent`) y `agent.py` (variable `app` o `root_agent`), y usa imports relativos dentro de él.

Documentación de TramiBot: [`adk_apps/adk_agenteia_tramibot_seguridad_model_armor/README.md`](adk_apps/adk_agenteia_tramibot_seguridad_model_armor/README.md)
