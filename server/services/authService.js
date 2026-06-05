const jwt = require('jsonwebtoken');
const User = require('../models/User');
const { AUTH } = require('../constants');

function buildToken(userId) {
  return jwt.sign({ userId }, process.env.JWT_SECRET, { expiresIn: AUTH.TOKEN_EXPIRY });
}

function userPayload(user) {
  return {
    _id:       user._id,
    name:      user.name,
    email:     user.email,
    role:      user.role,
    skillTags: user.skillTags,
    teamIds:   user.teamIds,
    createdAt: user.createdAt,
    updatedAt: user.updatedAt,
  };
}

async function register({ firstName, lastName, name, email, password, role, skillTags }) {
  const displayName = name?.trim() ||
    [firstName?.trim(), lastName?.trim()].filter(Boolean).join(' ');

  if (!displayName || !email || !password) {
    const err = new Error('Name (or first + last name), email and password are required.');
    err.statusCode = 400;
    throw err;
  }

  const existingUser = await User.findOne({ email: email.toLowerCase() });
  if (existingUser) {
    const err = new Error('Email already registered.');
    err.statusCode = 400;
    throw err;
  }

  const user = new User({
    name:         displayName,
    email:        email.toLowerCase(),
    passwordHash: password,
    role:         role || 'developer',
    skillTags:    Array.isArray(skillTags) ? skillTags : [],
  });

  await user.save();

  const token = buildToken(user._id);
  return { user: userPayload(user), token };
}

async function login(email, password) {
  if (!email || !password) {
    const err = new Error('Email and password are required.');
    err.statusCode = 400;
    throw err;
  }

  const user = await User.findOne({ email: email.toLowerCase() });
  if (!user) {
    const err = new Error('Invalid email or password.');
    err.statusCode = 401;
    throw err;
  }

  const isMatch = await user.comparePassword(password);
  if (!isMatch) {
    const err = new Error('Invalid email or password.');
    err.statusCode = 401;
    throw err;
  }

  const token = buildToken(user._id);
  return { user: userPayload(user), token };
}

module.exports = { register, login, userPayload, buildToken };
