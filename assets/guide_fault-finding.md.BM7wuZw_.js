import{_ as e,c as t,o as a,a4 as o}from"./chunks/framework.DAp7F7uL.js";const m=JSON.parse('{"title":"Fault finding","description":"","frontmatter":{},"headers":[],"relativePath":"guide/fault-finding.md","filePath":"guide/fault-finding.md","lastUpdated":1735380870000}'),n={name:"guide/fault-finding.md"},i=o(`<h1 id="fault-finding" tabindex="-1">Fault finding <a class="header-anchor" href="#fault-finding" aria-label="Permalink to &quot;Fault finding&quot;">​</a></h1><p>The addon follows the following process:</p><ol><li><p>Load all your sensor definitions. The logs will show if you use any unknown or deprecated sensors</p></li><li><p>Read the Inverter&#39;s serial number (and rated power)</p><p>If this read is successful, it will display the serial number</p><div class="language-txt vp-adaptive-theme"><button title="Copy Code" class="copy"></button><span class="lang">txt</span><pre class="shiki shiki-themes github-light github-dark vp-code" tabindex="0"><code><span class="line"><span>INFO    ############################################################</span></span>
<span class="line"><span>INFO                Inverter serial number &#39;*1234&#39;</span></span>
<span class="line"><span>INFO    ############################################################</span></span></code></pre></div></li><li><p>Connect to the MQQT server</p></li><li><p>Publish the discovery data for Home Assistant, and also remove discovery data if required</p></li></ol><p>After which it will continue to publish sensor data.</p><p>If you fail to get a reply from the inverter, typically if step #2 fails, please check the following:</p><h2 id="a-only-a-single-connection-to-the-serial-port" tabindex="-1">(a) Only a single connection to the serial port <a class="header-anchor" href="#a-only-a-single-connection-to-the-serial-port" aria-label="Permalink to &quot;(a) Only a single connection to the serial port&quot;">​</a></h2><p>Ensure you only have a single addon connected to the serial port. The following can all potentially access the USB port: mbusd, Node RED, the normal and dev addon version.</p><p>If you need to have multiple connections to the serial port: ONLY connect mbusd to the serial port. Connect all addons to mbusd (e.g. tcp://192.168.1.x:503).</p><h2 id="b-check-the-modbus-server-id" tabindex="-1">(b) Check the Modbus Server ID <a class="header-anchor" href="#b-check-the-modbus-server-id" aria-label="Permalink to &quot;(b) Check the Modbus Server ID&quot;">​</a></h2><p>Ensure the Modbus Server ID (<code>MODBUS_ID</code> config setting) matches the configured <strong>Modbus SN</strong> value of the inverter. This value must not be zero.</p><p>View/update the Modbus server ID on your inverter under &quot;Advanced Settings&quot; / &quot;Multi-Inverter&quot;.</p><p>Please note that this can be reset to zero after a software upgrade on your inverter, and this will stop the addon from reading data from your inverter. Resetting it to the previous value (the value the value in <code>MODBUS_ID</code> if you had this working previously), and then restarting the inverter should fix the <a href="https://powerforum.co.za/topic/15779-home-assistant-no-longer-getting-data-after-sunsynk-firmware-update-solved/" target="_blank" rel="noreferrer">issue</a>.</p><img src="https://github.com/kellerza/sunsynk/raw/main/images/modbus_sn.png" width="80%"><h2 id="c-reducing-timeouts" tabindex="-1">(c) Reducing timeouts <a class="header-anchor" href="#c-reducing-timeouts" aria-label="Permalink to &quot;(c) Reducing timeouts&quot;">​</a></h2><p>If you get many timeouts, or if the addon does not read all your sensors on startup (i.e. you see <strong>Retrying individual sensors</strong> in the log), you can try the following:</p><ul><li>Set <code>READ_SENSORS_BATCH_SIZE</code> to a smaller value, i.e. 8.</li><li>The most reliable way to connect is to use mbusd to the serial port &amp; connect the addon to mbusd at <code>tcp://&lt;ip&gt;:502</code>. The mbusd instance/addon can be on the same physical device or a remote device.</li></ul><p>The hardware and cabling also has a big impact:</p><ul><li>Use a RJ45 converter with a GROUND pin. Ensure the ground is connected.</li><li>Ensure the data line is on a twisted pair.</li><li>Re-crimp your RJ45 connector.</li><li>Use a good quality solid CAT5e/CAT6 cable.</li><li>Ensure your RS485 cable does not run parallel to other electrical cables (AC or DC), to reduce interference. e.g. in trunking. <ul><li>It could also help to use a shielded cable. Ground the shield at ONE end only (i.e. on the USB adaptor side and then just use normal platic RJ45 connector on the inverter side.</li><li>While fault finding use as short as possible cable, completely outside any sprague/trunking etc.</li></ul></li></ul><h2 id="d-check-line-voltage-termination-resistor" tabindex="-1">(d) Check line voltage / termination resistor <a class="header-anchor" href="#d-check-line-voltage-termination-resistor" aria-label="Permalink to &quot;(d) Check line voltage / termination resistor&quot;">​</a></h2><p>If your RS485 adapter has a termination resistor (typically 120 ohms), try removing it.</p><p>To check, disconnect the adapter and use a multimeter to measure the resistance between A &amp; B.</p><p>The d.c. voltage between A/B on the sunsynk RS485 connection should idle around 4-5v with nothing connected, but this may drop to around 0.5v with the 120 ohm load.</p><p>RS485 devices are typically multi-drop with a termination resistor on the first and last devices. However, the RS485 BMS port may only be intended to connect to a single device.</p><img src="https://github.com/kellerza/sunsynk/raw/main/images/rs485-term.jpg">`,24),s=[i];function r(l,d,c,u,h,p){return a(),t("div",null,s)}const f=e(n,[["render",r]]);export{m as __pageData,f as default};
