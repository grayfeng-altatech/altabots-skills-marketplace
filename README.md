# AltaBots Skills

Data-DI 內部的 AltaBots agent 開發 Claude Code skills 集合。

## altabots-version-archive

**你在 AltaBots 平台上做的 agent(客服機器人之類的東西),每次改版平台自己只會記住最近 10 次,超過就找不回來了,而且平台也沒辦法讓你把「某一版當時長什麼樣子」整個下載回來。等於你的 agent 改版歷史是會不見的。**

這個 skill 幫你做的事,用生活化比喻講:

### 1. 自動存底,永久不會不見
每次你改完一個 agent、要發布新版本,這個 skill 會自動幫你把這一版完整存起來,而且是永久保存,不會被蓋掉。就像你寫文件開了「版本歷史」功能,但這是專門為 AltaBots 的設定檔做的。

### 2. 自動幫你寫「這次改了什麼」
你不用自己回想或手動記錄「這次到底改了哪裡」,它會自動比對上一版跟這一版差在哪(哪個對話節點、哪句 prompt 被改了),自動幫你寫成一份清楚的紀錄,存在旁邊。

### 3. 一鍵存到雲端,不用自己開帳號設定
你只要說「幫我存到 XX 這個專案」,它會自動幫你在 GitHub(一個雲端硬碟)上開一個位置存進去,不用你自己跑去網站上點來點去。

### 4. 存之前會先確認,不會亂存
如果雲端已經有這個專案的存放位置,它會先問你「要存進這個既有的地方嗎」,而不是自己亂猜、亂新建一個造成重複。就算你講的名字跟雲端上實際的名字不完全一樣(比如你說「陽明海運」,但雲端上叫別的名字),它也會試著找出可能對應的地方給你確認,而不是直接告訴你「沒有」就自己新建一個。

### 5. 可以把舊版本要回來
萬一想看某個舊版本當時的內容,或想把舊版重新發布回平台,可以把它從存檔裡挖出來。

### 一句話總結
你以前要手動記錄改版歷史、還會因為平台限制丟失資料;現在只要正常做事,這個 skill 就在背後自動幫你把完整歷史存好、記清楚,而且存到雲端也不用自己動手設定。

## 安裝方式

```
/plugin marketplace add grayfeng-altatech/altabots-skills-marketplace
/plugin install altabots-version-archive@altabots-skills
```

裝完之後,直接用自然語言請 Claude 幫你存版本、比對差異、或存到雲端即可,不需要背指令。技術細節見 [`plugins/altabots-version-archive/skills/altabots-version-archive/SKILL.md`](plugins/altabots-version-archive/skills/altabots-version-archive/SKILL.md)。
