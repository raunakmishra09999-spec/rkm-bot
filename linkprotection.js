module.exports = {
    containsLink(content) {
        const urlRegex = /(https?:\/\/[^\s]+|discord\.gg\/[^\s]+|discord\.com\/invite\/[^\s]+)/gi;
        return urlRegex.test(content);
    },
    
    async handleLinkViolation(message, client) {
        await message.delete();
        
        try {
            await message.author.send(`⚠️ You have been **banned for 2 hours** from ${message.guild.name} for sending unauthorized links!`);
        } catch(e) {}
        
        await message.member.timeout(2 * 60 * 60 * 1000, 'Sending unauthorized links');
        
        const logChannel = message.guild.channels.cache.find(c => c.name === 'mod-logs');
        if (logChannel) {
            await logChannel.send(`🔨 ${message.author.tag} was timed out for 2 hours for sending: ${message.content}`);
        }
    }
};
