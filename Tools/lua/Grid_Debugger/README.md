Grid_Debugger
=================

Небольшой прототип инструментов для дебага YAML-маппингов.

Структура:
- src/Grid_Debugger.Core - библиотека с потоковой функцией удаления сущностей по UID
- src/Grid_Debugger.Validator - консольный валидатор прототипов (не использует render_shuttles.py)

Цель: быстрый итеративный инструмент для удаления конфликтных сущностей из маппинга.

Использование (пример):
dotnet run --project src/Grid_Debugger.Validator -- --file "path\to\map.yml"
