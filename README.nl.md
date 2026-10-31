<div align="center">

<img src="assets/icon.svg" width="110" alt="Virtual Battery-icoon">

# Virtual Battery

**Wat zou een thuisbatterij je opleveren? Zoek het uit voordat je er een koopt.**

Een Home Assistant-integratie die een thuisbatterij simuleert op dynamische stroomprijzen, je eigen zonnepanelen
en je eigen verbruik, en laat zien wat die batterij had opgebracht. Er wordt geen hardware aangestuurd.

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz)
[![Release](https://img.shields.io/github/v/release/onrust/virtual_battery)](https://github.com/onrust/virtual_battery/releases)
[![Licentie: MIT](https://img.shields.io/badge/licentie-MIT-green.svg)](LICENSE)

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/onrust)

*English version: [README.md](README.md)*

</div>

---

## Inhoud

1. [Wat doet het?](#wat-doet-het)
2. [Hoe werkt het?](#hoe-werkt-het)
3. [Vereisten](#vereisten)
4. [Installatie](#installatie)
5. [Instellen: wat vul je in en waarom](#instellen-wat-vul-je-in-en-waarom)
6. [Entiteiten](#entiteiten)
7. [Strategieën](#strategieën)
8. [Hoe de planner beslist](#hoe-de-planner-beslist)
9. [Dashboard](#dashboard)
10. [Tips en problemen oplossen](#tips-en-problemen-oplossen)
11. [Service](#service)
12. [Steun het project](#steun-het-project) · [Ontwikkeling](#ontwikkeling) · [Disclaimer](#disclaimer)

## Wat doet het?

* Berekent een **laad-/ontlaadschema** op de kwartierprijzen van vandaag en morgen (laden als het goedkoop is,
  ontladen als het duur is, met het rendementsverlies van 15 %, slijtage en de terugleverkorting erbij).
* Simuleert elke twee seconden wat een batterij **zou hebben gedaan** met je echte net- en zonnevermogen en houdt
  de **opbrengst van vandaag en totaal** bij alsof de batterij er was.
* Zes **strategieën**: prijsoptimalisatie, hybride (prijs + zelfverbruik), nul op de meter, nu opladen, nu ontladen en uit.
* **Zonvoorspelling met nowcast**: de voorspelling wordt bijgestuurd met wat je panelen de laatste uren echt leverden.
* Een zelflerend **verbruiksprofiel** (per weekdag en uur, exclusief je auto) uit je Home Assistant-statistieken.
* Een **minimale SoC (ondergrens)** waar de batterij nooit onder komt.
* Verwachte opbrengst voor vandaag en morgen, uitleg bij elke beslissing (de sensor *Reden*) en een kant-en-klaar dashboard.
* Nederlandse en Engelse namen, opties en redenteksten (volgt de taal van Home Assistant).

<p align="center">
  <img src="assets/screenshots/example-schedule.png" width="900"
       alt="Voorbeeld: prijsverloop met geplande laad- (blauw) en ontlaadmomenten (oranje) en de bijbehorende laadtoestand">
  <br><em>Voorbeeldplan voor 20 oktober 2026 (16 kWh / 7 kW, 5 % ondergrens): laden op goedkope zon rond de middag, ontladen in de avondpiek.
  Gemaakt door de planner op echte Nordpool-prijzen. Laden is blauw, ontladen oranje.</em>
</p>

## Hoe werkt het?

<p align="center">
  <img src="assets/screenshots/how-it-works.png" width="900" alt="Ingangen, planner en engine, uitgangen">
</p>

De integratie **leest alleen** je sensoren en schrijft nooit naar een apparaat, dus je kunt hem veilig naast je huidige
opstelling laten draaien. Twee onderdelen doen het werk:

1. **Planner**: berekent het dagschema opnieuw zodra er nieuwe prijzen zijn of je een instelling wijzigt. Bepaalt *wanneer*
   laden en ontladen loont.
2. **Engine**: draait elke 2 seconden. Volgt het schema, kijkt naar het actuele vermogen op je meter en omvormer en simuleert
   hoe de batterij zou reageren: laadtoestand, vermogen en wat dat bespaart of oplevert ten opzichte van geen batterij.

## Vereisten

| Wat | Waarom | Voorbeeld |
|---|---|---|
| Home Assistant **2025.1** of nieuwer met de **recorder** | statistieken worden gebruikt om je verbruik te leren en de zonvoorspelling bij te sturen | – |
| Een **Nordpool**-sensor met `raw_today` / `raw_tomorrow` (kwartier- of uurprijzen) | de prijzen sturen het hele plan | [Nordpool-integratie](https://github.com/custom-components/nordpool) |
| Je **all-in prijs**: Nordpool ingesteld met btw, energiebelasting en de opslag van je leverancier | de opbrengst wordt berekend met wat je echt betaalt en ontvangt per kWh | Nordpool met "additional costs"-template |
| **Netvermogen**: huidige afname en huidige teruglevering, in W of kW | om te weten wat het huis nu afneemt of teruglevert | Tibber Pulse, HomeWizard P1, DSMR |
| **Zonvermogen** (W/kW) en een **zonne-energieteller** (kWh) | actuele productie, en de echte opbrengst voor nowcast en je verbruiksprofiel | de integratie van je omvormer |
| **Tellers voor netafname en teruglevering** (kWh) | om je verbruiksprofiel uit de statistieken te leren | totaaltellers van je slimme meter |
| **Zonvoorspelling** voor vandaag en morgen, met het attribuut `wh_period_15m` | verwachte productie voor de planning | [Open-Meteo Solar Forecast](https://github.com/rany2/ha-open-meteo-solar-forecast) |
| Vermogen en energie van je laadpaal (optioneel) | zodat het laden van de auto je verbruiksprofiel niet vervuilt | Tesla Wall Connector, Easee, … |

> Het eigen icoon vereist Home Assistant 2026.3 of nieuwer; oudere versies tonen een tijdelijk plaatje.

## Installatie

### HACS (aanbevolen)

1. HACS → ⋮ → **Aangepaste repositories** → voeg `https://github.com/onrust/virtual_battery` toe, categorie **Integratie**.
2. Zoek **Virtual Battery**, kies **Downloaden** en **herstart Home Assistant**.
3. **Instellingen → Apparaten en diensten → Integratie toevoegen → Virtual Battery**.

### Handmatig

Kopieer de map `custom_components/virtual_battery` naar `<config>/custom_components/virtual_battery`,
herstart Home Assistant en voeg de integratie toe zoals hierboven.

## Instellen: wat vul je in en waarom

Het instellen heeft twee schermen. Alles van scherm 1 kun je later wijzigen via **Configureren** bij de integratie;
de getallen van scherm 2 worden entiteiten die je altijd kunt aanpassen.

### Scherm 1: sensoren

| Veld | Wat kies je | Waarom is dit nodig |
|---|---|---|
| **Naam** | Standaard `Virtual battery`. | Bepaalt de entiteit-id's: `sensor.<naam>_soc`, `number.<naam>_capacity`, … Kies een andere naam (bijv. "VB test") als je naast een andere batterijsimulatie wilt draaien. |
| **Nordpool prijssensor** | Je Nordpool-sensor, **all-in** (incl. btw, belasting, opslag). | Bron van de kwartier- (of uur)prijzen van vandaag en morgen. Planner en opbrengstberekening gebruiken deze. |
| **Actuele prijssensor** *(optioneel)* | Een sensor met de huidige all-in prijs per kWh. | Laat je dit leeg, dan wordt de huidige Nordpool-stand gebruikt. Alleen invullen als je een aparte, nauwkeurigere prijssensor hebt. |
| **Netafname (vermogen)** | De sensor met het vermogen dat je **afneemt** van het net, in **W of kW**. Voorbeeld (Tibber Pulse): `sensor.<woning>_power`. | Vertelt de engine hoeveel het huis nu van het net nodig heeft. De batterij zou dat afdekken. |
| **Teruglevering (vermogen)** | De sensor met het vermogen dat je **teruglevert**, in **W of kW**. Voorbeeld (Tibber Pulse): `sensor.<woning>_stroomproductie`. | Vertelt de engine hoeveel zonne-overschot er is om mee te laden, of hoeveel een ontlading aan je teruglevering toevoegt. |
| **Zonvermogen** | Actueel vermogen van je zonne-installatie (W/kW). | Nodig voor het echte huisverbruik (net + zon) en om uit overschot te laden. |
| **Zonne-energie (kWh-teller)** | De oplopende totaalteller van je zonopbrengst. | Voor de **nowcast** (voorspelling vs. werkelijkheid) en het verbruiksprofiel. Vereist langetermijnstatistieken (`state_class: total_increasing`). |
| **Netafname (kWh-teller)** | Totaal kWh afgenomen van het net. | Verbruiksprofiel (huisverbruik = afname + zon − teruglevering − auto). |
| **Teruglevering (kWh-teller)** | Totaal kWh teruggeleverd. | Idem. |
| **Laadpaal vermogen** *(optioneel)* | Vermogen van je laadpaal. | Laat engine en profiel de auto apart behandelen (zie *EV-beleid*). |
| **Laadpaal energie** *(optioneel)* | Totaal kWh van de laadpaal. | Haalt de auto uit het verbruiksprofiel, zodat het je *huis* leert en niet je auto. |
| **Zonvoorspelling vandaag / morgen** | De Open-Meteo Solar Forecast-sensoren "energy production today / tomorrow" (attribuut `wh_period_15m`). | Verwachte productie per kwartier. Geschaald met de **zon-zekerheid** en bijgestuurd door de nowcast. |
| **Zonvoorspelling resterend vandaag** *(optioneel)* | "Energy production remaining today". | De strategie *Nul op de meter* gebruikt dit om in te schatten hoeveel zon er nog komt. |

> **Let op:** de netsensoren moeten **vermogen** (W/kW) zijn, geen kosten- of energiesensoren. Een sensor met eenheid `EUR`
> of `kWh` geeft een betekenisloze simulatie.

### Scherm 2: batterij

| Veld | Standaard | Wat het betekent |
|---|---|---|
| **Capaciteit** | 8 kWh | Bruikbare capaciteit van de batterij die je wilt simuleren. |
| **Maximaal laad-/ontlaadvermogen** | 2,5 kW | Het meeste waarmee de batterij tegelijk kan laden of ontladen. |
| **Afschrijving per volledige cyclus** | 8 cent | Wat een volledige cyclus je aan slijtage kost. Een kWh laden kost `afschrijving / capaciteit`; de planner plant een cyclus alleen als die meer oplevert. |
| **Terugleverkorting** | € 0,11 / kWh | Wat je verliest per teruggeleverde kWh: het verschil tussen wat je voor een kWh betaalt en wat je voor een teruggeleverde kWh krijgt (terugleverkosten, einde van de salderingsregeling). Dit realistisch instellen is de belangrijkste keuze: het bepaalt of zonne-overschot opslaan beter is dan het terugleveren. |

Alle vier worden number-entiteiten, dus je kunt direct andere waarden proberen. Het rendement van heen-en-terug is vast op 85 %.

## Entiteiten

Entiteit-id's volgen `<domein>.<naam>_<sleutel>`, bijvoorbeeld `sensor.virtual_battery_soc` bij de standaardnaam.

### Sensoren

| Entiteit (sleutel) | Eenheid | Wat het zegt |
|---|---|---|
| `soc` | kWh | Nu opgeslagen energie. |
| `soc_percent` | % | Laadtoestand ten opzichte van de capaciteit. |
| `power` | W | Batterijvermogen nu: **+ laden, − ontladen**. |
| `charge_power` / `discharge_power` | W | Hetzelfde, gesplitst in twee positieve getallen (handig voor de power-flow-kaart). |
| `combined_power` | W | Batterijvermogen plus de laadpaal. |
| `house_consumption` | W | Echt verbruik van het huis: net + zon. |
| `effective_import` / `effective_export` | W | Wat je meter **met** batterij zou tonen. Vergelijk met de echte meter om het effect te zien. |
| `revenue_today` | € | Wat de batterij vandaag opbracht: je stroomrekening *zonder* batterij min *met*. Reset om middernacht. |
| `revenue_total` | € | Lopend totaal sinds de start. |
| `expected_revenue` | € | Verwachte eindopbrengst van vandaag. De attributen (`reeks`, `soc_reeks`, `laad_split`, `ontlaad_split`) voeden de dashboardgrafieken; `verwacht_morgen` bevat de verwachting voor morgen. |
| `average_cost` | €/kWh | Gewogen gemiddelde inkoopprijs van de energie in de batterij (energie onder de ondergrens telt niet mee). De engine ontlaadt alleen voor zelfverbruik als dit beter is dan het alternatief. |
| `settlement_price` | €/kWh | Wat de energie op dit moment "waard" was: positief bij laden (kosten), negatief bij ontladen (besparing). |
| `reason` | tekst | Uitleg in gewone taal van wat de batterij nu doet en waarom ("Ontladen @ 880 W — zelfverbruik nu (€0,391) is voordeliger dan de beste latere toepassing (€0,348)"). |
| `plan` | tekst | Welk plan de planner koos, *A* of *B* (zie onder), en het voordeel in €. |
| `schedule_code` | tekst | Het dagschema als compacte tekst: starttijd, dan een letter per kwartier: **I** niets, **L** laden, **O** ontladen. Gebruikt door het dashboard. |
| `solar_forecast` | kWh | Zonvoorspelling na nowcast-correctie (attributen: waarden per periode). |
| `expected_consumption` | W | Verwacht verbruik in dit uur uit het geleerde profiel; de attributen bevatten de hele week en de komende uren. |

### Getallen (jouw instellingen)

| Entiteit | Bereik | Betekenis |
|---|---|---|
| `capacity` | 1–100 kWh | Batterijcapaciteit. |
| `max_power` | 0,5–50 kW | Maximaal laad-/ontlaadvermogen. |
| `min_soc` | 0–50 % | **Ondergrens**: de batterij ontlaadt nooit onder dit niveau. De planner gebruikt alleen de ruimte erboven en de gemiddelde inkoopprijs negeert de energie eronder. 0 = uit. |
| `depreciation` | 0–100 cent | Slijtagekosten per volledige cyclus. |
| `feed_in_discount` | 0–1 €/kWh | Verlies per teruggeleverde kWh. |
| `min_margin` | 0–0,30 €/kWh | **Minimale winst per kWh** (standaard 3 ct). De planner plant een laad-/ontlaadcombinatie alleen als die per geladen kWh meer oplevert dan dit, na rendementsverlies en slijtage. Filtert kleine cycli weg die in standby- en omvormerverliezen meer kosten dan ze opleveren. 0 = uit. |
| `max_margin` | 0–1 €/kWh | Alleen *Nul op de meter*: hoeveel beter een latere verkoop moet zijn voordat de batterij nú *niet* uit overschot wordt geladen. Schaalt mee met de laadtoestand, dus een bijna volle batterij is terughoudender. |
| `solar_certainty` | 0–100 % | Hoeveel je de voorspelling vertrouwt. 100 % gebruikt hem zoals hij is, 60 % gaat uit van 60 % van de voorspelling. Lager = voorzichtiger plannen. |
| `profile_weeks` | 2–6 | Aantal weken waarover het verbruiksprofiel middelt. |
| `profile_weight_last` | 0–100 % | Extra gewicht van de laatste week (recente gewoontes tellen zwaarder). |
| `profile_mix` | 0–100 % | In hoeverre werkdagen en weekenddagen gemengd worden (0 = volledig gescheiden profielen). |

### Selecties

| Entiteit | Opties |
|---|---|
| `strategy` | Prijsoptimalisatie · Hybride (prijs + zelfverbruik) · Nul op de meter · Nu opladen · Nu ontladen · Uit |
| `ev_policy` | **Nooit** (de batterij mag de auto niet voeden) · **Alleen 's avonds/'s nachts** · **Altijd toegestaan (indien voordelig)**. Alleen van belang als je auto laadt. |

### Historie (dagarchief)

Elk kwartier bewaart de integratie één record (prijs, geladen/ontladen kWh, huis, zon, afname/teruglevering, opbrengst, laadtoestand, geplande actie en de reden) in `.storage`, één bestand per maand, **2 jaar** lang. Bij de eerste start worden de laatste ~10 dagen uit de recorder aangevuld (zonder geplande actie).

| Entiteit | Doel |
|---|---|
| `date.<naam>_view_date` | Kies een dag. Kies je vandaag, dan volgt hij weer vandaag. |
| `time.<naam>_view_time` | Kies een tijdstip (het bijbehorende kwartier wordt getoond). |
| `sensor.<naam>_day_view` | Stand = opbrengst van die dag (€). Attributen: totalen en reeksen per kwartier voor grafieken. Ververst na elk afgerond kwartier. |
| `sensor.<naam>_moment_view` | Stand = gemiddeld batterijvermogen in het gekozen kwartier (W, - = ontladen). Attributen: prijs, laadtoestand, geplande actie, reden enz. |

## Strategieën

| Strategie | Wat de gesimuleerde batterij doet |
|---|---|
| **Prijsoptimalisatie** | Volgt het dagschema: laadt in goedkope kwartieren, ontlaadt in de beste dure kwartieren. Als er voor het volgende laadmoment nog een beter moment komt, wacht hij. |
| **Hybride (prijs + zelfverbruik)** *(standaard)* | Als prijsoptimalisatie, maar dekt ook je eigen verbruik uit de batterij zodra je inkoopprijs hoger is dan de beste latere toepassing van de opgeslagen energie (verkopen, of je eigen verbruik dekken tegen de marktprijs van dat moment). Slaat ook zonne-overschot op als dat beter is dan terugleveren. |
| **Nul op de meter** | Klassiek thuisbatterijgedrag: laadt uit zonne-overschot (tenzij een latere verkoop duidelijk beter is, zie `max_margin`) en ontlaadt om de meter op nul te brengen. Heeft een noodklep in de middag voor een lage batterij. |
| **Nu opladen** / **Nu ontladen** | Vol vermogen tot vol of tot de ondergrens. Voor testen. |
| **Uit** | De batterij doet niets. |

## Hoe de planner beslist

* Hij kijkt naar **alle bekende kwartierprijzen** (vandaag, plus morgen zodra die bekend zijn) en koppelt goedkope *laad*-kwartieren aan latere dure *ontlaad*-kwartieren.
* Een paar loont alleen als `verkoopprijs × 0,85 − inkoopprijs − slijtage > minimale winst`. Rendementsverlies, slijtage en de **terugleverkorting** zitten in de berekening.
* Dezelfde toets geldt voor "nu het huis uit de batterij voeden en later goedkoop bijladen" (eerst ontladen, dan laden), bv. een avondpiek gevolgd door een nachtdal.
* Energie die je **huis zelf verbruikt** is de volle prijs waard; alleen wat je teruglevert is *prijs − terugleverkorting* waard. Het verwachte verbruik komt uit je eigen geleerde profiel.
* **Zonne-overschot** (voorspelling × zekerheid − verwacht verbruik) is goedkoop op te slaan, omdat het anders met korting zou worden teruggeleverd.
* Bestaande voorraad wordt eerst over de beste ontlaadkwartieren verdeeld.
* Bij verwachte zon worden twee plannen berekend: **A** (kijkt voor elke ontlading naar betaalde alternatieven) en **B** (verkoopt de voorraad simpelweg tegen de hoogste netto prijzen). A wordt alleen gekozen als dat meer dan € 0,10 beter is dan B.
* Een lopende laad- of ontlaadreeks wordt niet halverwege onderbroken.
* Met een **ondergrens** plant de planner op de ruimte erboven.

## Dashboard

De integratie bouwt een kant-en-klaar dashboard **met je eigen entiteiten** (drie weergaven: instellingen, voorspelling en historie). De kaarttitels zijn in het Nederlands.

<p align="center">
  <img src="assets/screenshots/dashboard-settings.png" width="900" alt="Instellingen: opbrengst, strategie, wat de batterij nu doet en alle instellingen"><br><em>Instellingen: opbrengst, strategie, wat de batterij nu doet en alle instellingen</em>
</p>

<p align="center">
  <img src="assets/screenshots/dashboard-forecast-1.png" width="900" alt="Voorspelling: verwachte zonopbrengst, energiestroom, batterijvermogen en laadtoestand"><br><em>Voorspelling: verwachte zonopbrengst, energiestroom, batterijvermogen en laadtoestand</em>
</p>

<p align="center">
  <img src="assets/screenshots/dashboard-forecast-2.png" width="900" alt="Voorspelling: gemiddeld huisverbruik per uur en verwacht verbruik tegenover zon voor de komende 24 uur"><br><em>Voorspelling: gemiddeld huisverbruik per uur en verwacht verbruik tegenover zon voor de komende 24 uur</em>
</p>

<p align="center">
  <img src="assets/screenshots/dashboard-forecast-3.png" width="900" alt="Voorspelling: prijs met het verwachte laad-/ontlaadschema en het dagsaldo met opbrengst"><br><em>Voorspelling: prijs met het verwachte laad-/ontlaadschema en het dagsaldo met opbrengst</em>
</p>

<p align="center">
  <img src="assets/screenshots/dashboard-history.png" width="900" alt="Historie: kies een dag en tijd, met totalen, het gekozen kwartier en grafieken van die dag"><br><em>Historie: kies een dag en tijd, met totalen, het gekozen kwartier en grafieken van die dag</em>
</p>

<p align="center">
  <img src="assets/screenshots/dashboard-history-tooltip.png" width="900" alt="Historie: beweeg over een staaf voor alle gegevens van dat kwartier; klik om het te kiezen"><br><em>Historie: beweeg over een staaf voor alle gegevens van dat kwartier; klik om het te kiezen</em>
</p>

**Vereist (via HACS, Frontend):** [apexcharts-card](https://github.com/RomRider/apexcharts-card) en [power-flow-card-plus](https://github.com/flixlix/power-flow-card-plus).

1. Ga naar **Ontwikkelaarsgereedschap → Acties**, kies **Virtual Battery: Dashboard genereren** en druk op **Actie uitvoeren**. In het antwoord staat het kant-en-klare dashboard; het wordt ook opgeslagen als `/config/virtual_battery/dashboard.yaml`.
2. Maak een nieuw dashboard: **Instellingen → Dashboards → Dashboard toevoegen → Nieuw dashboard vanaf nul** en open het.
3. Klik op het potlood (bewerken) → de drie puntjes → **Ruwe configuratie-editor**, verwijder wat er staat, plak het dashboard (kopieer het hele antwoord van de actie, of het bestand `dashboard.yaml`) en sla op.

Liever een dashboard dat vanzelf meebeweegt met de integratie? Zet dit in `configuration.yaml` en herstart (het dashboard is dan alleen-lezen in de interface):

```yaml
lovelace:
  dashboards:
    virtual-battery:
      mode: yaml
      title: Virtual battery
      icon: mdi:battery-heart-variant
      show_in_sidebar: true
      filename: virtual_battery/dashboard.yaml
```

Voer de actie na een update van de integratie opnieuw uit om het bestand te verversen.

## Tips en problemen oplossen

* **Opbrengst ziet er vreemd of negatief uit:** controleer of de Nordpool-sensor echt all-in is en of **netafname/teruglevering** vermogenssensoren zijn (geen kostensensoren).
* **Eenheden:** zowel W als kW wordt geaccepteerd voor de vermogenssensoren; de integratie rekent om.
* **Naast een bestaande implementatie draaien:** de integratie schrijft niets terug, geef hem gewoon een andere naam.
* **Het plan verandert elke paar minuten:** de planner rekent opnieuw bij nieuwe prijzen, instellingen of een nieuw profiel; de actie van het huidige blok is beschermd, dus een lopende reeks wordt niet afgebroken.
* **Nog geen verbruiksprofiel:** de eerste dagen geldt de terugvalwaarde (400 W) totdat er genoeg statistieken zijn (een paar weken geeft het beste resultaat).
* **Entiteit-id's:** gebaseerd op de naam die je invulde, niet op de taal, dus dashboards blijven werken als je de taal wijzigt.
* **Eén instantie:** er kan maar één Virtual Battery per Home Assistant worden ingesteld.

## Service

`virtual_battery.set_state`: stel de beginstand in (laadtoestand in kWh, gemiddelde kostprijs, totale en dagopbrengst),
bijvoorbeeld om de stand van een bestaande batterij of een eerdere simulatie over te nemen.

`virtual_battery.import_history` – vul het dagarchief aan uit de recorder-historie (`days`, standaard 10). Bestaande kwartieren blijven staan.

## Steun het project

Virtual Battery is gratis en open source. Bespaart het je geld of tijd, dan kun je een kopje koffie voor me kopen:

[![ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/onrust)

Ideeën, foutmeldingen en pull requests zijn van harte welkom in de [issue tracker](https://github.com/onrust/virtual_battery/issues).

## Ontwikkeling

```
python -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component
.venv/bin/python -m pytest
```

De rekenmodules zijn onafhankelijk van Home Assistant en staan in `custom_components/virtual_battery/logic/`.

## Disclaimer

Dit is een **simulatie** voor inzicht, geen financieel advies. De resultaten hangen af van de kwaliteit van je prijzen, voorspelling en instellingen,
en echte batterijen hebben extra verliezen en beperkingen (standby-verbruik, temperatuur, omvormerrendement, garantievoorwaarden).
