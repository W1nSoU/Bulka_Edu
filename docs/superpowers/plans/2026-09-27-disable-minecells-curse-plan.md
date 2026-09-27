# План реалізації: Відключення прокляття та миттєвої смерті від Проклятого меча

Цей план описує покроковий процес впровадження багаторівневого захисту через KubeJS для повного відключення ефекту `minecells:cursed` та скасування летальної шкоди від джерела `minecells.cursed`.

---

### Крок 1. Додати перехоплювач події Forge у startup-скрипт (`kubejs/startup_scripts/main.js`)
- [ ] Завантажити клас результату події:
  ```javascript
  const EventResult = Java.loadClass('net.minecraftforge.eventbus.api.Event$Result')
  ```
- [ ] Зареєструвати слухача події `net.minecraftforge.event.entity.living.MobEffectEvent$Applicable`:
  ```javascript
  ForgeEvents.onEvent('net.minecraftforge.event.entity.living.MobEffectEvent$Applicable', event => {
      let effect = event.getEffectInstance().getEffect()
      let effectId = effect.getDescriptionId()
      if (effectId === 'effect.minecells.cursed' || effectId === 'minecells:cursed') {
          event.setResult(EventResult.DENY)
      }
  })
  ```

---

### Крок 2. Додати серверні захисні обробники (`kubejs/server_scripts/main.js`)
- [ ] Додати обробник `PlayerEvents.tick` для негайного зняття ефекту, якщо він уже є на гравцеві:
  ```javascript
  PlayerEvents.tick(event => {
      let player = event.player
      if (player.hasEffect('minecells:cursed')) {
          player.removeEffect('minecells:cursed')
      }
  })
  ```
- [ ] Додати обробник `EntityEvents.hurt` для скасування шкоди від прокляття:
  ```javascript
  EntityEvents.hurt(event => {
      if (event.entity.isPlayer() && event.source.getMsgId() === 'minecells.cursed') {
          event.cancel()
      }
  })
  ```

---

### Крок 3. Перевірка та валідація
- [ ] Перевірити синтаксис змінених файлів (`startup_scripts/main.js` та `server_scripts/main.js`).
- [ ] Переконатися, що існуючі рецепти та конфігурації у файлах скриптів збережено неушкодженими.

---

### Крок 4. Фіксація змін та інструкція для гравця
- [ ] Зберегти зміни.
- [ ] Надати користувачеві інструкцію щодо активації: виконання `/reload` у грі (миттєвий захист від ваншоту) та перезапуск клієнта гри (для повної деактивації іконки ефекту через Forge startup-подію).
