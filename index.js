const { Client, GatewayIntentBits, Partials } = require('discord.js');
const fs = require('fs');
const sqlite3 = require('sqlite3').verbose();
const cron = require('node-cron');

const client = new Client({
    intents: [
        GatewayIntentBits.Guilds,
        GatewayIntentBits.GuildMessages,
        GatewayIntentBits.MessageContent,
        GatewayIntentBits.GuildMembers,
        GatewayIntentBits.MessageReactions,
        GatewayIntentBits.DirectMessages
    ],
    partials: [Partials.Channel, Partials.Message, Partials.Reaction]
});

const config = require('./config.json');

// Database setup
const db = new sqlite3.Database('./database/bot.db');
global.db = db;
global.config = config;

// Create database tables
db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        channelId TEXT,
        userId TEXT,
        teamName TEXT,
        players TEXT,
        timestamp INTEGER,
        slotNumber INTEGER
    )`);
    
    db.run(`CREATE TABLE IF NOT EXISTS match_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teamName TEXT,
        players TEXT,
        matchTime TEXT,
        matchDate TEXT,
        screenshot TEXT,
        isWin INTEGER,
        score INTEGER,
        week INTEGER,
        timestamp INTEGER
    )`);
    
    db.run(`CREATE TABLE IF NOT EXISTS weekly_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teamName TEXT,
        players TEXT,
        week INTEGER,
        wins INTEGER,
        top3Count INTEGER,
        totalScore INTEGER
    )`);
    
    db.run(`CREATE TABLE IF NOT EXISTS qualified_teams (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        teamName TEXT,
        players TEXT,
        qualificationDate INTEGER,
        roleAssigned INTEGER
    )`);
    
    db.run(`CREATE TABLE IF NOT EXISTS temp_registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tempId TEXT,
        userId TEXT,
        teamName TEXT,
        players TEXT,
        ffIds TEXT,
        whatsapp TEXT,
        timestamp INTEGER
    )`);
    
    db.run(`CREATE TABLE IF NOT EXISTS permanent_registrations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        userId TEXT,
        teamName TEXT,
        players TEXT,
        ffIds TEXT,
        whatsapp TEXT,
        paymentStatus INTEGER,
        timestamp INTEGER
    )`);
});

// Load all handlers
const reactionHandler = require('./handlers/reactionHandler');
const linkProtection = require('./handlers/linkProtection');
const registrationSystem = require('./handlers/registrationSystem');
const autoLockUnlock = require('./handlers/autoLockUnlock');
const matchRegistration = require('./handlers/matchRegistration');
const festivalBanner = require('./handlers/festivalBanner');
const resultAnalyzer = require('./handlers/resultAnalyzer');
const leaderboardSystem = require('./handlers/leaderboardSystem');
const qualificationSystem = require('./handlers/qualificationSystem');
const t2Registration = require('./handlers/t2RegistrationSystem');
const idpSystem = require('./handlers/idpSystem');

// Event: Message Create
client.on('messageCreate', async (message) => {
    if (message.author.bot) return;
    
    // 1. Auto reaction for team format channel
    if (message.channel.id === config.channels.teamFormat) {
        await reactionHandler.validateAndReact(message);
    }
    
    // 2. Link protection
    if (linkProtection.containsLink(message.content)) {
        await linkProtection.handleLinkViolation(message, client);
    }
    
    // 3. T3 Registration
    if (message.channel.parentId === config.channels.protectedCategory) {
        await registrationSystem.handleRegistration(message, client, db, config);
    }
    
    // 6. Result submission
    if (message.channel.id === config.channels.resultSubmit) {
        await resultAnalyzer.processResult(message, client, db, config);
    }
    
    // 8. T2 Registration
    if (message.channel.parentId === config.channels.t2Category) {
        await t2Registration.handleT2Registration(message, client, db, config);
    }
});

// Event: Interaction Create
client.on('interactionCreate', async (interaction) => {
    // 4. Match registration button
    if (interaction.channelId === config.channels.matchReg && interaction.isButton()) {
        await matchRegistration.handleMatchRegistration(interaction, client, db, config);
    }
    
    // IDP button
    if (interaction.customId === 'get_idp') {
        await idpSystem.sendIdp(interaction, client, db, config);
    }
    
    // Modal submit
    if (interaction.isModalSubmit() && interaction.customId === 'match_reg_form') {
        await matchRegistration.processRegistrationForm(interaction, client, db, config);
    }
});

// Event: Ready
client.once('ready', async () => {
    console.log(`✅ Bot is online as ${client.user.tag}`);
    
    // Initialize all systems
    await matchRegistration.sendRegistrationEmbed(client, config);
    festivalBanner.start(client, config);
    autoLockUnlock.init(client, db, config);
    
    // Schedule weekly leaderboard (Sunday 12 AM)
    cron.schedule('0 0 * * 0', async () => {
        await leaderboardSystem.generateWeeklyLeaderboard(client, db, config);
    });
    
    // Schedule qualification check (Monday 12 AM)
    cron.schedule('0 0 * * 1', async () => {
        await qualificationSystem.checkAndPromote(client, db, config);
    });
    
    console.log('✅ All systems initialized');
});

client.login(config.token);
