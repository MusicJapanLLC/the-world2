/**
 * P2P AGENT NETWORK
 * Direct communication between agents without god intermediation
 */

class P2PAgentNetwork {
  constructor() {
    this.messageQueue = [];
    this.agents = new Map();
    this.channels = new Map();
  }

  /**
   * Register agent in network
   */
  registerAgent(agentId, agent) {
    this.agents.set(agentId, agent);
    this.channels.set(agentId, []);
    return { registered: agentId };
  }

  /**
   * Send message from one agent to another
   */
  async sendMessage(fromAgent, toAgent, message) {
    if (!this.agents.has(fromAgent) || !this.agents.has(toAgent)) {
      return { error: 'Agent not found' };
    }

    const msg = {
      id: `msg_${Date.now()}_${Math.random()}`,
      from: fromAgent,
      to: toAgent,
      message,
      timestamp: Date.now(),
      status: 'sent'
    };

    this.messageQueue.push(msg);
    this.channels.get(toAgent).push(msg);

    return {
      messageId: msg.id,
      sent: true,
      timestamp: msg.timestamp
    };
  }

  /**
   * Receive messages for an agent
   */
  receiveMessages(agentId) {
    const messages = this.channels.get(agentId) || [];
    const result = [...messages];

    // Clear queue for agent
    this.channels.set(agentId, []);

    return result;
  }

  /**
   * Broadcast message to all agents
   */
  async broadcast(fromAgent, message) {
    const results = [];

    for (const toAgent of this.agents.keys()) {
      if (toAgent !== fromAgent) {
        const result = await this.sendMessage(fromAgent, toAgent, message);
        results.push(result);
      }
    }

    return {
      broadcastId: `bc_${Date.now()}`,
      recipientCount: results.length,
      results
    };
  }

  /**
   * Create direct channel between two agents
   */
  createChannel(agent1, agent2) {
    const channelId = `channel_${agent1}_${agent2}`;
    this.channels.set(channelId, { agent1, agent2, messages: [] });
    return { channelId, agents: [agent1, agent2] };
  }

  /**
   * Get network statistics
   */
  getNetworkStats() {
    return {
      agentCount: this.agents.size,
      totalMessages: this.messageQueue.length,
      activeChannels: this.channels.size,
      messagesByAgent: this.getMessageCounts()
    };
  }

  /**
   * Count messages per agent
   */
  getMessageCounts() {
    const counts = new Map();

    for (const [agentId] of this.agents) {
      const sent = this.messageQueue.filter(m => m.from === agentId).length;
      const received = this.messageQueue.filter(m => m.to === agentId).length;
      counts.set(agentId, { sent, received });
    }

    return Object.fromEntries(counts);
  }

  /**
   * Enable direct p2p mode (agents communicate without god)
   */
  enableP2PMode() {
    return {
      enabled: true,
      mode: 'peer-to-peer',
      description: 'Agents can now communicate directly without intermediation'
    };
  }

  /**
   * Get communication graph (which agents communicate with whom)
   */
  getCommunicationGraph() {
    const graph = new Map();

    for (const msg of this.messageQueue) {
      if (!graph.has(msg.from)) {
        graph.set(msg.from, []);
      }
      graph.get(msg.from).push(msg.to);
    }

    return Object.fromEntries(graph);
  }
}

export default P2PAgentNetwork;
