# План реалізації: Відключення прокляття та миттєвої смерті від Проклятого меча

Цей план описує покроковий процес впровадження багаторівневого захисту через KubeJS для повного відключення ефекту `minecells:cursed` та скасування летальної шкоди від джерела `minecells.cursed`.

---

### Крок 1. Додати перехоплювач події Forge у startup-скрипт (`kubejs/startup_scripts/main.js`)
- [x] Завантажити клас результату події:
  ```javascript
  const EventResult = Java.loadClass('net.minecraftforge.eventbus.api.Event$Result')
  ```
- [x] Зареєструвати слухача події `net.minecraftforge.event.entity.living.MobEffectEvent$Applicable`:
  ```javascript
  ForgeEvents.onEvent('net.minecraftforge.event.entity.living.MobEffectEvent$Applicable', event => {
      let effectInstance = event.getEffectInstance()
      if (!effectInstance) return
      let effect = effectInstance.getEffect()
      if (!effect) return
      let effectId = effect.getDescriptionId()
      if (effectId === 'effect.minecells.cursed' || effectId === 'minecells:cursed') {
          event.setResult(EventResult.DENY)
      }
  })
  ```

---

### Крок 2. Додати серверні захисні обробники (`kubejs/server_scripts/main.js`)
- [x] Додати обробник `PlayerEvents.tick` для негайного зняття ефекту, якщо він уже є на гравцеві:
  ```javascript
  PlayerEvents.tick(event => {
      let player = event.player
      if (!player) return
      if (player.hasEffect('minecells:cursed')) {
          player.removeEffect('minecells:cursed')
      }
  })
  ```
- [x] Додати обробник `EntityEvents.hurt` для скасування шкоди від прокляття:
  ```javascript
  EntityEvents.hurt(event => {
      if (event.entity && event.entity.isPlayer() && event.source) {
          let msgId = event.source.getMsgId()
          if (msgId === 'minecells.cursed' || msgId === 'minecells:cursed' || msgId === 'cursed') {
              event.cancel()
          }
      }
  })
  ```

---

### Крок 3. Перевірка та валідація
- [x] Перевірити синтаксис змінених файлів (`startup_scripts/main.js` та `server_scripts/main.js`).
- [x] Переконатися, що існуючі рецепти та конфігурації у файлах скриптів збережено неушкодженими.

---

### Крок 4. Фіксація змін та інструкція для гравця
- [x] Зберегти зміни.
- [x] Надати користувачеві інструкцію щодо активації: виконання `/reload` у грі (миттєвий захист від ваншоту) та перезапуск клієнта гри (для повної деактивації іконки ефекту через Forge startup-подію).

